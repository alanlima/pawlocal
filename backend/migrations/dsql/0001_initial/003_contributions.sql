CREATE TABLE IF NOT EXISTS contributions (
    id uuid PRIMARY KEY,
    kind varchar(32) NOT NULL CHECK (kind IN ('review', 'location_suggestion', 'tip', 'correction')),
    place_id uuid REFERENCES places(id),
    rating integer CHECK (rating IS NULL OR (rating >= 1 AND rating <= 5)),
    body text NOT NULL CHECK (length(body) BETWEEN 1 AND 5000) CHECK (length(trim(BOTH E' \t\n\r\f\v' FROM body)) >= 1),
    contributor_subject varchar(255) NOT NULL,
    is_published boolean NOT NULL DEFAULT true,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CHECK ((kind = 'review' AND place_id IS NOT NULL AND rating IS NOT NULL) OR (kind <> 'review' AND rating IS NULL))
);
