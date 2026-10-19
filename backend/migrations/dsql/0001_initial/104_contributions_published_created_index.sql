CREATE INDEX ASYNC IF NOT EXISTS ix_contributions_published_created ON contributions (is_published, created_at);
