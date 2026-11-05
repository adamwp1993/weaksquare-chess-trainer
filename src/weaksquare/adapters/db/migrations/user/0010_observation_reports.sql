-- user.db v10 (v0.11, QA v0.11-B3): which reports have seen each observation, so a report seen again after
-- another one isn't counted twice (FR-10.57). Never edit this file once applied; add 0011_… instead.
ALTER TABLE coach_observations ADD COLUMN report_ids TEXT NOT NULL DEFAULT '[]';

UPDATE coach_observations
SET report_ids = CASE
    WHEN first_report_id IS NULL THEN '[]'
    WHEN last_report_id IS NULL OR last_report_id = first_report_id THEN json_array(first_report_id)
    ELSE json_array(first_report_id, last_report_id)
END;
