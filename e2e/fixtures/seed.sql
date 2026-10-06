-- Seed data for E2E tests
-- All datetimes are UTC naive (no timezone), stored as ISO strings.
-- "now" in tests = 2026-10-06 12:00:00 UTC

-- Sources
INSERT INTO sources (id, name, kind, is_official, enabled) VALUES
  (1, 'yahoo_rss',  'rss', 0, 1),
  (2, 'reuters_rss', 'rss', 0, 1);

-- Articles
-- Active NVDA article within 24h
INSERT INTO articles (id, source_id, publisher, title, url, canonical_url, published_at, fetched_at, tickers_raw, raw_payload, clean_text, injection_score, matched_rules, status) VALUES
  (1, 1, 'Yahoo Finance', 'NVIDIA Reports Record Q3 Revenue', 'https://finance.yahoo.com/nvda-q3', 'https://finance.yahoo.com/nvda-q3', '2026-10-06 08:00:00', '2026-10-06 08:05:00', '["NVDA"]', '{}', 'NVIDIA reported record revenue of $35.08 billion, growing 122% year-over-year.', 0.0, '[]', 'active'),
-- Active opinion article (NVDA, for show_opinions toggle test)
  (2, 2, 'Reuters', 'Analyst: NVDA Momentum Continues', 'https://reuters.com/nvda-opinion', 'https://reuters.com/nvda-opinion', '2026-10-06 09:00:00', '2026-10-06 09:05:00', '["NVDA"]', '{}', 'Barclays analyst says NVDA momentum continues in data center.', 0.0, '[]', 'active'),
-- Quarantined article (should not appear on dashboard)
  (3, 1, 'Spam Source', 'Buy NVDA now! Limited offer!!!', 'https://spam.example.com/promo', 'https://spam.example.com/promo', '2026-10-06 07:00:00', '2026-10-06 07:05:00', '["NVDA"]', '{}', 'Buy NVDA now! Best deal!!!', 0.92, '["promo_pattern"]', 'quarantined'),
-- Active article for unverified story (AAPL)
  (4, 1, 'Yahoo Finance', 'Apple Announces New Product Line', 'https://finance.yahoo.com/aapl-new', 'https://finance.yahoo.com/aapl-new', '2026-10-06 06:00:00', '2026-10-06 06:05:00', '["AAPL"]', '{}', 'Apple announced a new product line at its fall event.', 0.0, '[]', 'active');

-- Fetch runs
INSERT INTO fetch_runs (id, source_id, started_at, finished_at, status, items_seen, items_new, newest_item_at) VALUES
  (1, 1, '2026-10-06 08:00:00', '2026-10-06 08:00:30', 'completed', 10, 4, '2026-10-06 08:00:00'),
  (2, 2, '2026-10-06 09:00:00', '2026-10-06 09:00:20', 'completed', 5, 2, '2026-10-06 09:00:00');

-- Story clusters
-- Cluster 1: NVDA verified story
INSERT INTO story_clusters (id, primary_ticker, first_seen_at, last_seen_at, article_count, publisher_count, event_type, is_main_subject, is_opinion, relevance_score, visible, classification_model, classification_prompt_version) VALUES
  (1, 'NVDA', '2026-10-06 08:00:00', '2026-10-06 09:00:00', 2, 2, 'earnings', 1, 0, 0.95, 1, 'claude-haiku-4-5', 'classify_v1:ab12cd34');

-- Cluster 2: NVDA opinion story (for show_opinions test)
INSERT INTO story_clusters (id, primary_ticker, first_seen_at, last_seen_at, article_count, publisher_count, event_type, is_main_subject, is_opinion, relevance_score, visible, classification_model, classification_prompt_version) VALUES
  (2, 'NVDA', '2026-10-06 09:00:00', '2026-10-06 09:00:00', 1, 1, 'analyst_opinion', 1, 1, 0.8, 1, 'claude-haiku-4-5', 'classify_v1:ab12cd34');

-- Cluster 3: AAPL unverified story (pending verification)
INSERT INTO story_clusters (id, primary_ticker, first_seen_at, last_seen_at, article_count, publisher_count, event_type, is_main_subject, is_opinion, relevance_score, visible, classification_model, classification_prompt_version) VALUES
  (3, 'AAPL', '2026-10-06 06:00:00', '2026-10-06 06:00:00', 1, 1, 'product_launch', 1, 0, 0.7, 1, 'claude-haiku-4-5', 'classify_v1:ab12cd34');

-- Cluster members
INSERT INTO cluster_members (cluster_id, article_id, match_method, similarity, needs_llm_check) VALUES
  (1, 1, 'exact_hash', 1.0, 0),
  (1, 2, 'minhash', 0.85, 0),
  (2, 2, 'exact_hash', 1.0, 0),
  (3, 4, 'exact_hash', 1.0, 0);

-- Stories
-- Story 1: verified NVDA story
INSERT INTO stories (id, cluster_id, title_bg, summary_bg, tickers, event_type, is_opinion, verification_status, model_version, prompt_version, created_at) VALUES
  (1, 1, 'NVIDIA отчете рекордни приходи за Q3 2024', 'NVIDIA обяви приходи от $35.08 млрд., ръст от 122% спрямо година по-рано.', '["NVDA"]', 'earnings', 0, 'verified', 'claude-sonnet-4-6', 'summarize_v1:ef56gh78', '2026-10-06 10:00:00');

-- Story 2: opinion NVDA story (hidden by default, shown only with show_opinions=true)
INSERT INTO stories (id, cluster_id, title_bg, summary_bg, tickers, event_type, is_opinion, verification_status, model_version, prompt_version, created_at) VALUES
  (2, 2, 'Анализатор: импулсът на NVIDIA продължава', 'Анализатор от Barclays: "We see continued momentum in data center."', '["NVDA"]', 'analyst_opinion', 1, 'verified', 'claude-sonnet-4-6', 'summarize_v1:ef56gh78', '2026-10-06 10:05:00');

-- Story 3: pending (unverified) AAPL story
INSERT INTO stories (id, cluster_id, title_bg, summary_bg, tickers, event_type, is_opinion, verification_status, model_version, prompt_version, created_at) VALUES
  (3, 3, 'Apple обяви нова продуктова линия', 'Apple представи нови продукти на есенното си събитие.', '["AAPL"]', 'product_launch', 0, 'pending', 'claude-sonnet-4-6', 'summarize_v1:ef56gh78', '2026-10-06 10:10:00');

-- Story facts
INSERT INTO story_facts (id, story_id, fact_order, text_bg, verification_status) VALUES
  (1, 1, 0, 'Приходите нараснали с 122% спрямо година по-рано до $35.08 млрд.', 'verified'),
  (2, 1, 1, 'Нетната печалба надхвърли очакванията на анализаторите', 'verified');

-- Fact evidence (verbatim quotes from articles)
INSERT INTO fact_evidence (id, fact_id, article_id, quote_en, quote_start, quote_end) VALUES
  (1, 1, 1, 'NVIDIA reported record revenue of $35.08 billion, growing 122% year-over-year.', 0, 72),
  (2, 2, 1, 'NVIDIA reported record revenue of $35.08 billion, growing 122% year-over-year.', 0, 72);

-- Verification log (one passing, one failing)
INSERT INTO verification_log (id, story_id, fact_id, check, passed, details, created_at) VALUES
  (1, 1, 1, 'quote_exists', 1, NULL, '2026-10-06 10:30:00'),
  (2, 1, 2, 'number_in_source', 0, 'Number 122% not found verbatim', '2026-10-06 10:30:00');

-- LLM calls (for costs)
INSERT INTO llm_calls (id, purpose, model, prompt_version, input_tokens, output_tokens, cost_usd, latency_ms, status, created_at) VALUES
  (1, 'classify',  'claude-haiku-4-5',  'classify_v1:ab12cd34',  500,  100, 0.03, 800, 'ok', '2026-10-06 09:00:00'),
  (2, 'summarize', 'claude-sonnet-4-6', 'summarize_v1:ef56gh78', 1000, 500, 0.07, 2000, 'ok', '2026-10-06 10:00:00');
