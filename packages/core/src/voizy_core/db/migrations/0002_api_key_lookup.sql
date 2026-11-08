-- API key authentication happens before the workspace is known. Rather than a SECURITY DEFINER
-- function, expose exactly the row whose hash the caller already holds, read-only.
-- Permissive policies are OR-ed with tenant_isolation, so this adds no other visibility.
CREATE POLICY api_key_lookup ON api_keys FOR SELECT
  USING (key_hash = decode(nullif(current_setting('app.api_key_hash', true), ''), 'hex'));
