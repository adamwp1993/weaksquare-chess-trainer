-- user.db v12 (v0.12, QA v0.12-B6): when you ticked a task by hand, so the daily log can count it on that day
-- (FR-10.68). Never edit this file once applied; add 0013_… instead.
ALTER TABLE plan_tasks ADD COLUMN manual_at TEXT;
