# turns a question into the chunks Claude answers from: always 8 in total
# 1. semester lookup: a question naming a semester gets that program chunk in slot 1
# 2. the retriever (v1: vector search) fills the remaining k slots
# v2 (full-text + vector, merged by Reciprocal Rank Fusion) and v3 (+ prerequisites) are added here later

from app import voyage
from app.text import find_semester

TOTAL_CHUNKS = 8


#the program chunk a question names ("3rd semester", "part-time semester 2", co-op work terms), or None
def lookup_chunk(conn, question):
    found = find_semester(question)
    if found is None:
        return None
    semester, format = found
    row = conn.execute(
        "select id from chunks where format = %s and semester is not distinct from %s",
        (format, semester),
    ).fetchone()
    return row[0] if row else None


#the question's embedding (input_type "query", same model as the chunks)
def embed_question(question):
    return voyage.embed([question], "query")[0]


#v1: the k chunks closest to the question by cosine distance (exact search, no index)
def retrieve_v1(conn, question, vector, k, exclude):
    vector = "[" + ",".join(map(str, vector)) + "]"
    rows = conn.execute(
        """
        select id from chunks
        where not (id = any(%s))
        order by embedding <=> %s::vector
        limit %s
        """,
        (exclude, vector, k),
    ).fetchall()
    return [row[0] for row in rows]


RETRIEVERS = {"v1": retrieve_v1}


#the 8 chunks for a (code-normalized) question, in rank order, with their page url
#vector: the question's embedding if already computed (eval reuses one per question across versions)
def retrieve(conn, question, retriever="v1", vector=None):
    if vector is None:
        vector = embed_question(question)
    ids = []
    looked_up = lookup_chunk(conn, question)
    if looked_up is not None:
        ids.append(looked_up)
    ids += RETRIEVERS[retriever](conn, question, vector, TOTAL_CHUNKS - len(ids), ids)

    rows = conn.execute(
        """
        select c.id, c.content, d.url, d.kind
        from chunks c join documents d on d.id = c.document_id
        where c.id = any(%s)
        """,
        (ids,),
    ).fetchall()
    by_id = {row[0]: {"id": row[0], "content": row[1], "url": row[2], "kind": row[3]} for row in rows}
    return [by_id[i] for i in ids]
