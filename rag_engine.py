import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from dotenv import load_dotenv
import boto3
from langchain_huggingface import HuggingFaceEmbeddings
# from langchain_ollama import OllamaLLM
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_aws import ChatBedrock, BedrockEmbeddings,ChatBedrockConverse
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_classic.text_splitter import RecursiveCharacterTextSplitter
from langchain_classic.chains import RetrievalQA
from langchain_core.prompts import PromptTemplate
from langchain_core.prompts import ChatPromptTemplate
from langchain_classic.chains.combine_documents.stuff import create_stuff_documents_chain
from langchain_classic.chains.retrieval import create_retrieval_chain

# Configuration
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
api_key = os.getenv("OPENAI_API_KEY")
CHROMA_PATH = "./chroma_db"
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
_EMBEDDINGS = None
REGION = os.getenv("AWS_REGION", "ap-south-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_SESSION_TOKEN = os.getenv("AWS_SESSION_TOKEN")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
BEDROCK_BASE_MODEL_ID = os.getenv("BEDROCK_BASE_MODEL_ID", BEDROCK_MODEL_ID)
BEDROCK_INFERENCE_PROFILE_ID = os.getenv("BEDROCK_INFERENCE_PROFILE_ID")

def get_bedrock_client():
    client_kwargs = {"region_name": REGION}

    # Prefer repo-local credentials from `.env` so the app does not depend on
    # a machine-specific AWS CLI profile. Falls back to boto3's default chain.
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        client_kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
        client_kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
        if AWS_SESSION_TOKEN:
            client_kwargs["aws_session_token"] = AWS_SESSION_TOKEN

    return boto3.client("bedrock-runtime", **client_kwargs)


def get_embeddings():
    global _EMBEDDINGS

    if _EMBEDDINGS is not None:
        return _EMBEDDINGS

    try:
        _EMBEDDINGS = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME)
        return _EMBEDDINGS
    except Exception as exc:
        raise RuntimeError(
            "Unable to load the Hugging Face embedding model "
            f"'{EMBEDDING_MODEL_NAME}'. If the model is not cached locally, "
            "download it once with internet access and an optional HF_TOKEN."
        ) from exc

def fetch_all_cis_points(os_type="linux"):
    """
    Fetches all unique CIS points with their titles from ChromaDB for the specified OS.
    
    Args:
        os_type (str): The OS type to filter by ('linux' or 'windows')
    
    Returns:
        list: List of dictionaries with 'id' and 'title' keys
              Example: [{'id': '1.1.1.3', 'title': 'Ensure hfs kernel module is not available (Automated)'}]
    """
    import re
    
    normalized_os = (os_type or "linux").strip().lower()
    if normalized_os not in {"linux", "windows"}:
        normalized_os = "linux"

    db = Chroma(persist_directory=CHROMA_PATH, embedding_function=get_embeddings())
    collection = db._collection

    # Fetch documents with metadata and filter in Python so OS matching is
    # resilient to casing differences in stored metadata.
    results = collection.get(include=["documents", "metadatas"])
    
    cis_points = []
    seen_ids = set()
    
    # Pattern to match CIS entries: "1.1.1.3 Title description (Optional status)"
    # Matches format like: "1.1.1.3 Ensure hfs kernel module is not available (Automated)"
    pattern = r'^(\d+\.\d+(?:\.\d+)*)\s+(.+?)(?:\n|$)'
    
    for doc, metadata in zip(results.get("documents", []), results.get("metadatas", [])):
        metadata_os = str((metadata or {}).get("os_type", "")).strip().lower()
        if metadata_os != normalized_os:
            continue

        lines = doc.split('\n')
        for line in lines:
            line = line.strip()
            match = re.match(pattern, line)
            if match and line[0].isdigit():  # Ensure starts with a digit
                cis_id = match.group(1)
                title = match.group(2).strip()
                
                # Only add if we haven't seen this ID before and title is meaningful
                if cis_id not in seen_ids and len(title) > 5:
                    cis_points.append({
                        "id": cis_id,
                        "title": title
                    })
                    seen_ids.add(cis_id)
    
    # Sort by CIS ID for better readability
    cis_points.sort(key=lambda x: [int(n) for n in x['id'].split('.')])
    return cis_points

def _normalize_control_text(text):
    normalized = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    return " ".join(normalized.split())

def find_matching_cis_points(query, os_type="linux", limit=3, min_score=0.45):
    """
    Finds the closest CIS control titles for a user prompt so the app can show
    the matching CIS IDs for validation.
    """
    normalized_query = _normalize_control_text(query)
    if not normalized_query:
        return []

    matches = []
    for point in fetch_all_cis_points(os_type):
        normalized_title = _normalize_control_text(point["title"])
        if not normalized_title:
            continue

        score = SequenceMatcher(None, normalized_query, normalized_title).ratio()

        # Boost strong partial matches, which is common for control-title prompts.
        if normalized_query in normalized_title or normalized_title in normalized_query:
            score = max(score, 0.92)

        if score >= min_score:
            matches.append({
                "id": point["id"],
                "title": point["title"],
                "score": score
            })

    matches.sort(key=lambda item: (-item["score"], [int(n) for n in item["id"].split(".")]))
    return matches[:limit]

def _clean_script_output(script_text):
    """Removes Markdown fences so script fragments can be stitched together safely."""
    cleaned = script_text.strip()
    cleaned = re.sub(r"^```(?:bash|sh|powershell|ps1)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()

def _build_batch_query(cis_points, os_type):
    script_type = "bash" if os_type == "linux" else "powershell"
    formatted_points = "\n".join(
        f"- CIS {point['id']}: {point['title']}" for point in cis_points
    )
    return (
        f"Generate a {script_type} hardening script for {os_type} covering exactly these CIS controls.\n"
        f"{formatted_points}\n"
        "Return only runnable script content. Include comments for each CIS ID and avoid Markdown code fences."
    )

def _generate_script_for_batch(cis_points, os_type):
    query = _build_batch_query(cis_points, os_type)
    retrieval_k = min(max(len(cis_points) * 3, 25), 120)
    result = run_rag_query(query, os_type, k=retrieval_k)
    return _clean_script_output(result)

def generate_master_script_from_cis_points(os_type="linux", progress_callback=None):
    """
    Builds a master hardening script by first enumerating all CIS controls
    available for the requested OS and then asking the RAG pipeline to
    generate a combined script for that explicit control set.

    Args:
        os_type (str): The OS type to filter by ('linux' or 'windows')

    Returns:
        str: Generated master script or a user-friendly fallback message
    """
    cis_points = fetch_all_cis_points(os_type)

    if not cis_points:
        return f"No CIS controls found in the vector database for {os_type}."

    batch_size = 25
    total_batches = (len(cis_points) + batch_size - 1) // batch_size
    batched_scripts = []
    processed_controls = 0

    for index in range(0, len(cis_points), batch_size):
        batch = cis_points[index:index + batch_size]
        batch_number = (index // batch_size) + 1
        script_fragment = _generate_script_for_batch(batch, os_type)
        batched_scripts.append((batch_number, batch, script_fragment))
        processed_controls += len(batch)
        if progress_callback:
            progress_callback(
                batch_number,
                total_batches,
                len(cis_points),
                processed_controls,
                batch
            )

    if os_type == "linux":
        header = [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            f"# Master CIS hardening script for {os_type}",
            f"# Total CIS controls requested: {len(cis_points)}",
            f"# Generated in {total_batches} batches",
            ""
        ]
    else:
        header = [
            "# Master CIS hardening script for windows",
            f"# Total CIS controls requested: {len(cis_points)}",
            f"# Generated in {total_batches} batches",
            ""
        ]

    merged_script = "\n".join(header)

    for batch_number, batch, script_fragment in batched_scripts:
        start_id = batch[0]["id"]
        end_id = batch[-1]["id"]
        merged_script += (
            f"\n# Batch {batch_number}: CIS {start_id} to CIS {end_id}\n"
            f"{script_fragment}\n"
        )

    return merged_script.strip() + "\n"

def ingest_document(file_path, os_type):
    print(f"Ingesting document for OS: {os_type} from file: {file_path}")
    """Loads a PDF, tags it with OS metadata, and stores in ChromaDB."""
    loader = PyPDFLoader(file_path)
    print("loading doc")
    try:
        documents = loader.load()
    except Exception as exc:
        raise RuntimeError(f"Failed to load document: {exc}") from exc
    print("loading doc completed ")
    # Add metadata to help the LLM filter context
    for doc in documents:
        doc.metadata["os_type"] = os_type

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)
    chunks = text_splitter.split_documents(documents)
    
    # Using Bedrock's Titan for Embeddings
    # embeddings = BedrockEmbeddings(client=get_bedrock_client(), region_name=REGION)
    
    # vector_db = Chroma.from_documents(
    #     documents=chunks, 
    #     embedding=embeddings, 
    #     persist_directory=CHROMA_PATH
    # )
    vector_db = Chroma.from_documents(
            documents=chunks,
            embedding=get_embeddings(),
            persist_directory=CHROMA_PATH
        )
    return vector_db

def run_rag_query(query, os_type, k=10, score_threshold=None, include_validation=False):

    """Retrieves context and uses Bedrock to generate the script."""
    # embeddings = BedrockEmbeddings(client=get_bedrock_client(), region_name=REGION)
    db = Chroma(persist_directory=CHROMA_PATH, embedding_function=get_embeddings())
    
    # Bedrock Model (Claude 3.5 Sonnet is highly recommended for scripting)
    # llm = ChatBedrock(
    #     model_id="anthropic.claude-3-5-sonnet-20240620-v1:0",
    #     client=get_bedrock_client(),
    #     model_kwargs={"temperature": 0}
    # )
    # guardrail_config = {
    #     "guardrailIdentifier": "5em67sj8whjs", # From AWS Console
    #     "guardrailVersion": "DRAFT",                    # Use a numeric version or DRAFT
    #     "trace": "enabled"                          # Useful for debugging why a block happened
    # }
    print("env",BEDROCK_INFERENCE_PROFILE_ID,BEDROCK_MODEL_ID)
    effective_model_id = BEDROCK_INFERENCE_PROFILE_ID or BEDROCK_MODEL_ID

    llm = ChatBedrockConverse(
        model_id=effective_model_id,
        client=get_bedrock_client(),
        region_name=REGION,
        temperature=0,
        # base_model_id helps LangChain understand the underlying model architecture
        base_model_id=BEDROCK_BASE_MODEL_ID
        # guardrail_config=guardrail_config
    )
    script_type = "PowerShell" if os_type == "windows" else "Bash"

    template = f"""
    System: You are an expert Cloud Security Engineer. Use ONLY the provided CIS context to generate hardening scripts.
    
    Context: {{context}}
    User Request: {{question}}

    Rules:
    1. Generate a {script_type} script for {os_type}.
    2. The hardening points are for {os_type}.
    3. For Windows, output a clean, runnable PowerShell (.ps1) script.
    4. For Linux, output a clean, runnable Bash (.sh) script.
    5. If the user asks for 'all' or multiple points, combine them into one structured script.
    6. Always include comments for each hardening ID (e.g., # CIS 1.1.1).
    7. If the provided context does not contain relevant CIS hardening information for the query, respond with: "No relevant hardening controls found for this query. Please provide a query related to CIS benchmarks."

    Response:
    """
    
    prompt = PromptTemplate(template=template, input_variables=["context", "question"])
    # llm = ChatOpenAI(model="gpt-4", temperature=0)
    
    validation_matches = find_matching_cis_points(query, os_type) if include_validation else []

    if score_threshold is not None:
        retriever = db.as_retriever(
            search_type="similarity_score_threshold", 
            search_kwargs={"k": k, "score_threshold": score_threshold, "filter": {"os_type": os_type}}
        )
    else:
        retriever = db.as_retriever(search_kwargs={"k": k, "filter": {"os_type": os_type}})
    
    # Check if any relevant documents are retrieved
    if score_threshold is not None:
        results = db.similarity_search_with_score(query, k=k, filter={"os_type": os_type})
        retrieved_docs = []
        for doc, score in results:
            print(f"Retrieved doc score: {score:.4f}")  # Debug logging
            if score <= score_threshold:
                retrieved_docs.append(doc)
    else:
        results = db.similarity_search_with_score(query, k=k, filter={"os_type": os_type})
        retrieved_docs = [doc for doc, score in results]
        print(f"Retrieved {len(retrieved_docs)} docs for broad query, scores: {[f'{score:.4f}' for _, score in results]}")  # Debug logging
    if 'No relevant docs were retrieved' in retrieved_docs:
        print('Nod docs found')
    else:
        print('found docs')
    if not retrieved_docs:
        return "No relevant hardening controls found for this query. Please provide a query related to CIS benchmarks."
    else:
        
        chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            chain_type_kwargs={"prompt": prompt}
        )
        print( "Retrieved relevant documents, generating script...")
        result = chain.invoke({"query": query})["result"]

        if not include_validation or not validation_matches:
            return result

        validation_lines = [
            "Validation from vector DB:",
            *[
                f"- CIS {match['id']}: {match['title']}"
                for match in validation_matches
            ],
            "",
            result
        ]
        return "\n".join(validation_lines)
