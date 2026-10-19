CREATE TABLE IF NOT EXISTS places (
    id uuid PRIMARY KEY,
    name varchar(200) NOT NULL CHECK (length(trim(name)) > 0),
    category varchar(32) NOT NULL CHECK (category IN ('dog_park', 'beach', 'walk', 'hiking_area', 'cafe')),
    area varchar(160) NOT NULL,
    address varchar(300),
    description text,
    dog_access_rules text,
    average_rating double precision CHECK (average_rating IS NULL OR (average_rating >= 1 AND average_rating <= 5)),
    source_updated_at timestamp with time zone,
    is_published boolean NOT NULL DEFAULT false,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);
