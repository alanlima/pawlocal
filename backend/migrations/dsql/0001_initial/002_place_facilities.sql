CREATE TABLE IF NOT EXISTS place_facilities (
    place_id uuid NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    facility varchar(80) NOT NULL CHECK (facility IN ('Fenced', 'Off-leash area', 'Drinking water', 'Shade', 'Picnic tables', 'Accessible paths')),
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (place_id, facility)
);
