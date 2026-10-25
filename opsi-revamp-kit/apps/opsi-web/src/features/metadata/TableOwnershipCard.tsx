// Small, reusable catalog card (owners, domains, PII tags) for incident and service pages.
// This is an Opsi-native component: OpenMetadata's own UI components are not imported (see
// docs/consultations/02-openmetadata-deployment-and-integration.md "UI reuse matrix").
import { useEffect, useState } from "react";

import { type CatalogEntity, catalogApi } from "./catalogApi";

export function TableOwnershipCard({ fqn, openMetadataUiBase }: { fqn: string; openMetadataUiBase?: string }) {
  const [entity, setEntity] = useState<CatalogEntity | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    catalogApi.table(fqn).then((e) => !cancelled && setEntity(e)).catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [fqn]);

  if (error) return <div role="alert">Catalog unavailable: {error}</div>;
  if (!entity) return <div aria-busy="true">Loading catalog…</div>;
  const pii = entity.tags.filter((t) => t.toUpperCase().startsWith("PII"));
  return (
    <section className="opsi-catalog-card" aria-label={`Catalog entry ${entity.fqn ?? fqn}`}>
      <h4>{entity.name}</h4>
      <dl>
        <dt>Owners</dt><dd>{entity.owners.join(", ") || "unassigned"}</dd>
        <dt>Domain</dt><dd>{entity.domains.join(", ") || "—"}</dd>
        {pii.length > 0 && (<><dt>Sensitivity</dt><dd>{pii.join(", ")}</dd></>)}
      </dl>
      {openMetadataUiBase && entity.fqn && (
        <a href={`${openMetadataUiBase}/table/${encodeURIComponent(entity.fqn)}`} target="_blank" rel="noreferrer noopener">
          Open in OpenMetadata
        </a>
      )}
    </section>
  );
}
