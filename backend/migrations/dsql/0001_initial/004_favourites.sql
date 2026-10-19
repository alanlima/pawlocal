CREATE TABLE IF NOT EXISTS favourites (
    user_subject varchar(255) NOT NULL,
    place_id uuid NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    PRIMARY KEY (user_subject, place_id)
);
