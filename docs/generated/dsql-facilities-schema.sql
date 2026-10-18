CREATE TABLE places (
	id UUID NOT NULL,
	name VARCHAR(200) NOT NULL,
	is_published BOOLEAN NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE place_facilities (
	place_id UUID NOT NULL,
	ordinal INTEGER NOT NULL,
	facility VARCHAR(80) NOT NULL,
	PRIMARY KEY (place_id, ordinal),
	CONSTRAINT ck_place_facilities_ordinal CHECK (ordinal >= 0),
	CONSTRAINT ck_place_facilities_value CHECK (facility IN ('Accessible paths', 'Drinking water', 'Fenced', 'Off-leash area', 'Picnic tables', 'Shade')),
	FOREIGN KEY(place_id) REFERENCES places (id) ON DELETE CASCADE
);

CREATE INDEX ASYNC ix_place_facilities_facility_place ON place_facilities (facility, place_id);
