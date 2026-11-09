-- The other party's phone number, kept with the call so operators can see who it was.
-- It is personal data: the API masks it unless the reader holds calls:view_pii, and it expires with
-- the call like everything else. Transcripts still redact numbers spoken aloud.
ALTER TABLE calls ADD COLUMN remote_number text CHECK (remote_number ~ '^\+[1-9][0-9]{6,14}$');
