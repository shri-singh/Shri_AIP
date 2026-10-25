-- Rollback 0004: DROPS the ontology (entities, edges, catalog cross-references).
DO $$ BEGIN
  IF current_setting('opsi.allow_destructive', true) IS DISTINCT FROM 'yes' THEN
    RAISE EXCEPTION 'Refusing destructive rollback. Take a snapshot first, then run: SET opsi.allow_destructive = ''yes'';';
  END IF;
END $$;

DROP FUNCTION IF EXISTS opsi_knowledge.neighborhood(uuid, timestamptz, int, int);
DROP TABLE IF EXISTS opsi_knowledge.catalog_xrefs, opsi_knowledge.edges, opsi_knowledge.entities,
  opsi_knowledge.relation_types, opsi_knowledge.entity_kinds;
