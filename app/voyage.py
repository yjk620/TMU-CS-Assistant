# Voyage AI embeddings over plain HTTP, shared by ingest (input_type "document") and /ask ("query")
# so both sides always use the same model and size

import logging
import os
import time

import httpx

log = logging.getLogger("voyage")

URL = "https://api.voyageai.com/v1/embeddings"
MODEL = "voyage-4-lite"
DIMENSIONS = 1024
#small enough for the free tier (no payment method: ~10k tokens per minute); ~4 characters per token
MAX_TEXTS = 128
MAX_CHARS = 32_000
RETRIES = 5


#split texts into batches of at most 128 texts and ~32k characters
def batches(texts):
    batch, chars = [], 0
    for text in texts:
        if batch and (len(batch) == MAX_TEXTS or chars + len(text) > MAX_CHARS):
            yield batch
            batch, chars = [], 0
        batch.append(text)
        chars += len(text)
    if batch:
        yield batch


#one request; retries rate limits (429), server errors (5xx) and network errors with a growing wait
def embed_batch(client, texts, input_type):
    payload = {"input": texts, "model": MODEL, "input_type": input_type, "output_dimension": DIMENSIONS}
    for attempt in range(1, RETRIES + 1):
        try:
            response = client.post(URL, json=payload)
        except httpx.TransportError as error:
            problem = repr(error)
        else:
            if response.status_code != 429 and response.status_code < 500:
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda d: d["index"])
                return [d["embedding"] for d in data]
            problem = f"HTTP {response.status_code}"
        wait = 20 * attempt
        log.warning("voyage %s, retry %d/%d in %ds", problem, attempt, RETRIES, wait)
        time.sleep(wait)
    raise RuntimeError(f"Voyage failed {RETRIES} times")


#embed texts in batches; returns one list of 1024 floats per text, in the same order
def embed(texts, input_type):
    headers = {"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}"}
    vectors = []
    with httpx.Client(headers=headers, timeout=60) as client:
        for batch in batches(texts):
            vectors.extend(embed_batch(client, batch, input_type))
            if len(texts) > MAX_TEXTS:
                log.info("embedded %d/%d", len(vectors), len(texts))
    return vectors
