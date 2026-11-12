-- pgvector: adds the vector type and the <=> cosine-distance operator used for retrieval.
create extension if not exists vector;

-- documents: one row per fetched page (curriculum, elective tables, courses, dates, policies).
-- Holds the raw HTML so ingest.py can re-chunk without re-crawling. Upserted on url.
create table documents (
  id          serial primary key,
  url         text unique not null,
  kind        text not null check (kind in ('program','elective_table','course','date','policy')),
  title       text not null,
  html        text not null,                   -- raw page, so ingest can re-parse without re-crawling
  fetched_at  timestamptz not null
);

-- courses: one row per course page, with its prerequisites. Filled by scrape.py; used to
-- follow prerequisites during the crawl and by the v3 retriever to pull in prerequisite pages.
create table courses (
  code          text primary key,              -- 'CPS 803', 'CCPS 109'
  document_id   int not null references documents(id),
  prereq_text   text,                          -- the Prerequisites field as written
  prereq_codes  text[] not null default '{}'   -- codes parsed from prereq_text only
);

-- chunks: the retrievable units. Each has its text, embedding (vector search) and tsv (full-text search).
-- semester/format let /ask fetch a program semester directly. Replaced per document on re-ingest.
create table chunks (
  id            serial primary key,
  document_id   int not null references documents(id) on delete cascade,
  content       text not null,                 -- course codes already in 'CPS 803' form
  content_hash  text not null,                 -- sha256 of content; reuse embeddings on re-ingest
  semester      int check (semester between 1 and 8),                     -- program chunks only; null for co-op schedule
  format        text check (format in ('four-year','part-time','co-op')), -- program chunks only
  embedding     vector(1024) not null,         -- voyage-4-lite default output size
  -- course codes become one token ('CPS 803' -> 'CPS803') so full-text search matches them exactly
  tsv           tsvector generated always as (
                  to_tsvector('english', regexp_replace(content, '\m([A-Z]{3,4}) (\d{3})\M', '\1\2', 'g'))
                ) stored
);

-- GIN index on tsv: keeps full-text search (v2, v3) fast.
create index on chunks using gin (tsv);
-- No vector index: at ~2-3k chunks, exact search with cosine distance (<=>) is fast and gives exact results.

-- queries: log of every /ask call (web and eval): question, retrieved chunks, answer, refusal flag.
-- Used for debugging and for the usage count (source = 'web').
create table queries (
  id         serial primary key,
  asked_at   timestamptz not null default now(),
  source     text not null check (source in ('web','eval')),
  retriever  text not null,
  question   text not null,
  chunk_ids  int[] not null,                   -- logs only: ids change after a re-ingest
  answer     text not null,
  refused    boolean not null
);
