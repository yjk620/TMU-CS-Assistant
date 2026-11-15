# turns a question into the chunks Claude answers from: always 8 in total
# 1. semester lookup: a question naming a semester gets that program chunk in slot 1
# 2. the retriever (v1: vector search) fills the remaining k slots
#    v1: vector search
#    v2: full-text search + vector search, merged by Reciprocal Rank Fusion
#    v3: v2's top k-3, plus up to 3 prerequisite courses of the course chunks in it

import re

from app import voyage
from app.text import find_semester

TOTAL_CHUNKS = 8
CANDIDATES = 20  #how many chunks each ranking contributes to the v2 merge
PREREQ_SLOTS = 3 #v3: how many slots go to prerequisite courses
RRF_K = 60       #the standard Reciprocal Rank Fusion constant: score = 1 / (60 + rank)
#a course code in stored form ("CPS 803"); same pattern the tsv column uses to join codes into one token
STORED_CODE_RE = re.compile(r"\b([A-Z]{3,4}) (\d{3})\b")


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


#"CPS 803" -> "CPS803", matching how the tsv column stores codes (one token, "cps803")
def join_codes(text):
    return STORED_CODE_RE.sub(r"\1\2", text)


#the question's course codes as tsv tokens, e.g. "cps714 | cps406" ("" if there are none)
def code_tokens(question):
    return " | ".join(f"{letters.lower()}{number}" for letters, number in STORED_CODE_RE.findall(question))


#full-text ranking. websearch_to_tsquery joins words with AND, which fails on natural questions
#("need & take & cps843" matches nothing), so words are OR-ed instead. ts_rank doesn't weigh rare words
#above common ones, so chunks containing one of the question's course codes rank first,
#then ts_rank on all the words breaks ties (normalized by chunk length)
def text_ranked(conn, question, limit, exclude):
    rows = conn.execute(
        """
        with q as (
            select cast(replace(cast(websearch_to_tsquery('english', %(text)s) as text), '&', '|') as tsquery) as words,
                   cast(nullif(%(codes)s, '') as tsquery) as codes
        )
        select id from chunks, q
        where tsv @@ q.words and not (id = any(%(exclude)s))
        order by coalesce(tsv @@ q.codes, false) desc, ts_rank(tsv, q.words, 1) desc, id
        limit %(limit)s
        """,
        {"text": join_codes(question), "codes": code_tokens(question), "exclude": exclude, "limit": limit},
    ).fetchall()
    return [row[0] for row in rows]


#Reciprocal Rank Fusion: each id scores 1 / (60 + rank) in every ranking it appears in; highest total first.
#Uses ranks only, so cosine distance and ts_rank (different scales) never need comparing.
#Ties keep the order of first appearance (vector ranking first)
def rrf(*rankings):
    scores = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, 1):
            scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (RRF_K + rank)
    return sorted(scores, key=lambda chunk_id: -scores[chunk_id])


#the vector top 20 and the full-text top 20, merged (up to 40 ids, best first)
def v2_ranking(conn, question, vector, exclude):
    by_vector = retrieve_v1(conn, question, vector, CANDIDATES, exclude)
    by_text = text_ranked(conn, question, CANDIDATES, exclude)
    return rrf(by_vector, by_text)


#v2: the best k of the merged ranking
def retrieve_v2(conn, question, vector, k, exclude):
    return v2_ranking(conn, question, vector, exclude)[:k]


#v3 selection rules, no database access (prereqs_of: chunk id -> its course's prereq codes, in order;
#chunk_of: course code -> that course's chunk id):
#1. keep the ranking's top k-3
#2. walk those in rank order; for each course chunk, add the chunk of each prerequisite in order,
#   skipping codes with no course page and chunks already selected (or excluded, e.g. the semester slot);
#   stop after 3 additions
#3. fill any slots left from the ranking's next chunks
def expand_with_prereqs(ranking, k, prereqs_of, chunk_of, exclude=()):
    top = ranking[:max(k - PREREQ_SLOTS, 0)]
    selected = list(top)
    taken = set(top) | set(exclude)
    added = 0
    for chunk_id in top:
        for code in prereqs_of.get(chunk_id, []):
            if added == PREREQ_SLOTS:
                break
            prereq = chunk_of.get(code)
            if prereq is None or prereq in taken:
                continue
            selected.append(prereq)
            taken.add(prereq)
            added += 1
    for chunk_id in ranking[len(top):]:
        if len(selected) == k:
            break
        if chunk_id not in taken:
            selected.append(chunk_id)
            taken.add(chunk_id)
    return selected


#v3: v2's top k-3 plus up to 3 prerequisite course chunks, then v2's next ranks
def retrieve_v3(conn, question, vector, k, exclude):
    ranking = v2_ranking(conn, question, vector, exclude)
    top = ranking[:max(k - PREREQ_SLOTS, 0)]
    #prerequisite codes of the course chunks among the top
    prereqs_of = dict(conn.execute(
        """
        select ch.id, co.prereq_codes
        from chunks ch join courses co on co.document_id = ch.document_id
        where ch.id = any(%s)
        """,
        (top,),
    ).fetchall())
    #the chunk of each of those prerequisite courses (codes with no course page are simply absent)
    codes = sorted({code for codes in prereqs_of.values() for code in codes})
    chunk_of = dict(conn.execute(
        """
        select co.code, ch.id
        from courses co join chunks ch on ch.document_id = co.document_id
        where co.code = any(%s)
        """,
        (codes,),
    ).fetchall())
    return expand_with_prereqs(ranking, k, prereqs_of, chunk_of, exclude)


RETRIEVERS = {"v1": retrieve_v1, "v2": retrieve_v2, "v3": retrieve_v3}


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
