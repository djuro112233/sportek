"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useT } from "@/lib/i18n";
import { useAdminUser } from "@/components/admin/AdminContext";
import { getValidationItem, getVillages } from "@/components/admin/api";
import ItemDetail from "@/components/admin/ItemDetail";
import ProvenanceTimeline from "@/components/admin/ProvenanceTimeline";
import TransitionPanel from "@/components/admin/TransitionPanel";
import { ITEM_TYPES, type Status } from "@/components/admin/types";
import { ErrorAlert, LiveMessage, Loading, Section, StatusBadge, UnverifiedFlag } from "@/components/admin/ui";
import { useAsync } from "@/components/admin/useAsync";

function firstString(v: unknown): string {
  return typeof v === "string" ? v : "";
}

/** One item of the queue: every field, its provenance trail and the transitions this role may perform. */
export default function ValidationItemPage() {
  const t = useT();
  const params = useParams<{ itemType: string; id: string }>();
  const itemType = String(params?.itemType ?? "");
  const id = String(params?.id ?? "");
  const { user } = useAdminUser();
  const [done, setDone] = useState<string | null>(null);

  const villagesQ = useAsync(() => getVillages(), []);
  const itemQ = useAsync(() => getValidationItem(itemType, id), [itemType, id]);

  const known = (ITEM_TYPES as string[]).includes(itemType);
  const payload = itemQ.data;
  const item = payload?.item ?? null;
  const status = (firstString(item?.status) || "draft") as Status;
  const factsVerified = typeof item?.facts_verified === "boolean" ? (item.facts_verified as boolean) : null;
  const titleLocal = firstString(item?.title_local) || firstString(item?.name_local);
  const titleEn = firstString(item?.title_en) || firstString(item?.name_en);

  return (
    <div className="stack">
      <p>
        <Link href="/validate">{t("admin.item.backToQueue")}</Link>
      </p>

      {!known && (
        <p className="alert alert-danger" role="alert">
          {t("admin.item.unknownType", { type: itemType })}
        </p>
      )}

      {itemQ.loading && <Loading />}
      <ErrorAlert error={itemQ.error} onRetry={itemQ.reload} />
      <LiveMessage message={done} />

      {payload && item && (
        <>
          <section className="card">
            <h1 style={{ marginTop: 0 }}>
              <span lang="cnr">{titleLocal || t("admin.queue.untitled")}</span>
              {titleEn && titleEn !== titleLocal && (
                <>
                  {" "}
                  <span className="muted" lang="en" style={{ fontWeight: 400 }}>
                    / {titleEn}
                  </span>
                </>
              )}
            </h1>
            <p className="row">
              <span>{t(`admin.itemType.${payload.item_type}`)}</span>
              <StatusBadge status={status} />
              <span className="muted small">{t("admin.item.versionShort", { version: firstString(item.version) || String(item.version ?? "") })}</span>
              <UnverifiedFlag verified={factsVerified !== false} />
            </p>
          </section>

          <Section id="fields" title={t("admin.item.fields")} lead={t("admin.item.fieldsLead")}>
            <ItemDetail itemType={payload.item_type} item={item} villages={villagesQ.data ?? []} />
          </Section>

          <Section id="provenance" title={t("admin.item.provenance")} lead={t("admin.item.provenanceLead")}>
            <ProvenanceTimeline provenance={payload.provenance ?? []} />
          </Section>

          <Section id="decision" title={t("admin.item.decision")}>
            <TransitionPanel
              itemType={payload.item_type}
              itemId={id}
              status={status}
              role={user.role}
              factsVerified={factsVerified}
              onDone={(to) => {
                setDone(t("admin.transition.done", { status: t(`admin.status.${to}`) }));
                itemQ.reload();
              }}
            />
          </Section>
        </>
      )}
    </div>
  );
}
