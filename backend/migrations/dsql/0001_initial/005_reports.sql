CREATE TABLE IF NOT EXISTS reports (
    id uuid PRIMARY KEY,
    target_type varchar(20) NOT NULL CHECK (target_type IN ('place', 'contribution')),
    target_place_id uuid REFERENCES places(id),
    target_contribution_id uuid REFERENCES contributions(id),
    reporter_subject varchar(255) NOT NULL,
    reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 2000) CHECK (length(trim(BOTH E' \t\n\r\f\v' FROM reason)) >= 1),
    status varchar(20) NOT NULL DEFAULT 'pending',
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CHECK ((target_type = 'place' AND target_place_id IS NOT NULL AND target_contribution_id IS NULL) OR (target_type = 'contribution' AND target_contribution_id IS NOT NULL AND target_place_id IS NULL))
);
