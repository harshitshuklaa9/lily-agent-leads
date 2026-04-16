-- Add 'insights' to the buyer_type check constraint on contacts.
-- Required after adding the insights buyer persona to the stakeholder search.

ALTER TABLE contacts DROP CONSTRAINT IF EXISTS contacts_buyer_type_check;

ALTER TABLE contacts
  ADD CONSTRAINT contacts_buyer_type_check
  CHECK (buyer_type IN ('technical', 'business', 'insights'));
