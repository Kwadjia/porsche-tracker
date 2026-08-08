import { getSql, json, type Env } from "../../../_shared";

// GET /api/vehicles/:id/history — full observation history across all of a
// vehicle's listings (price/mileage lineage over time and across sources).
export const onRequestGet: PagesFunction<Env> = async ({ env, params }) => {
  const sql = getSql(env);
  const id = Number(params.id);
  if (!Number.isFinite(id)) return json({ error: "bad vehicle id" }, 400);

  const observations = await sql`
    select l.id         as listing_id,
           l.source_id  as source_id,
           o.observed_at,
           o.price::float as price,
           o.mileage,
           o.status
    from listing_observations o
    join listings l on l.id = o.listing_id
    where l.vehicle_id = ${id}
    order by o.observed_at asc
  `;
  return json({ vehicle_id: id, observations });
};
