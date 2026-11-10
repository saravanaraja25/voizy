-- A finished campaign keeps its history after the phone number it used is disconnected.
-- The number is remembered as text, and the link is cleared automatically when the number is removed.
-- (Running, paused and draft campaigns still block disconnecting; the API checks that first.)

ALTER TABLE campaigns ADD COLUMN from_number text
  CHECK (from_number ~ '^\+[1-9][0-9]{6,14}$');
UPDATE campaigns c SET from_number = n.e164
  FROM phone_numbers n WHERE n.workspace_id = c.workspace_id AND n.id = c.from_number_id;
ALTER TABLE campaigns ALTER COLUMN from_number_id DROP NOT NULL;

CREATE FUNCTION detach_campaigns_from_number() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE campaigns SET from_number_id = NULL
   WHERE workspace_id = OLD.workspace_id AND from_number_id = OLD.id;
  RETURN OLD;
END
$$;
CREATE TRIGGER phone_numbers_detach_campaigns BEFORE DELETE ON phone_numbers
  FOR EACH ROW EXECUTE FUNCTION detach_campaigns_from_number();
