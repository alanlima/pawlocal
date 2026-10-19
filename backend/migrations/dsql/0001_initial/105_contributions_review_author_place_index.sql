CREATE UNIQUE INDEX ASYNC IF NOT EXISTS uq_contributions_review_author_place ON contributions (contributor_subject, place_id) WHERE kind = 'review' AND place_id IS NOT NULL;
