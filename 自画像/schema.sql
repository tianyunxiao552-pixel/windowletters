CREATE TABLE bangumi_reviews (
    subject_id INTEGER PRIMARY KEY,
    media_type TEXT NOT NULL,
    title TEXT NOT NULL,
    original_title TEXT NOT NULL,
    collection_status TEXT NOT NULL,
    personal_rating INTEGER CHECK(personal_rating BETWEEN 1 AND 10),
    personal_review TEXT NOT NULL,
    collection_updated_at TEXT,
    work_url TEXT NOT NULL,
    user_collection_url TEXT NOT NULL,
    CHECK(personal_rating IS NOT NULL OR LENGTH(TRIM(personal_review)) > 0)
);

CREATE TABLE bilibili_posts (
        post_id TEXT PRIMARY KEY,
        article_id TEXT,
        kind TEXT NOT NULL,
        published_at TEXT,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        detail_status TEXT NOT NULL CHECK(detail_status IN ('full', 'preview')),
        source_url TEXT NOT NULL,
        blocks_json TEXT NOT NULL
    );

CREATE TABLE evidence (
            id INTEGER PRIMARY KEY,
            post_id TEXT NOT NULL REFERENCES sources(post_id),
            quote TEXT NOT NULL,
            UNIQUE(post_id, quote)
        );

CREATE TABLE item_evidence (
            item_id INTEGER NOT NULL REFERENCES items(id),
            sort_order INTEGER NOT NULL,
            evidence_id INTEGER NOT NULL REFERENCES evidence(id),
            PRIMARY KEY(item_id, sort_order)
        );

CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            label TEXT NOT NULL UNIQUE,
            statement TEXT NOT NULL,
            basis TEXT NOT NULL CHECK (basis IN ('本人自述', '本人观点', '跨帖归纳', '表达样本')),
            context TEXT NOT NULL
        );

CREATE TABLE profile (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

CREATE TABLE sources (
            post_id TEXT PRIMARY KEY,
            published_at TEXT NOT NULL,
            type TEXT NOT NULL,
            page_title TEXT NOT NULL,
            url TEXT NOT NULL
        );

CREATE INDEX bangumi_reviews_rating ON bangumi_reviews(personal_rating, media_type, title);

CREATE INDEX bilibili_posts_date ON bilibili_posts(published_at DESC);
