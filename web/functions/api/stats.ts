import { getSql, json, type Env } from "../_shared";

// GET /api/stats — dashboard summary. Mirrors the FastAPI reference endpoint.
export const onRequestGet: PagesFunction<Env> = async ({ env }) => {
  const sql = getSql(env);

  const [{ active_listings }] = (await sql`
    select count(*)::int as active_listings from listings where status = 'active'
  `) as { active_listings: number }[];

  const [{ active_vehicles }] = (await sql`
    select count(distinct vehicle_id)::int as active_vehicles
    from listings where status = 'active'
  `) as { active_vehicles: number }[];

  const [{ total, vinned }] = (await sql`
    select count(*)::int as total, count(vin)::int as vinned from vehicles
  `) as { total: number; vinned: number }[];

  // median latest asking price per active listing, grouped by trim
  const medians = (await sql`
    with latest as (
      select distinct on (o.listing_id) o.listing_id, o.price
      from listing_observations o
      join listings l on l.id = o.listing_id and l.status = 'active'
      order by o.listing_id, o.observed_at desc
    )
    select v.trim,
           percentile_cont(0.5) within group (order by la.price)::float as median
    from latest la
    join listings l on l.id = la.listing_id
    join vehicles v on v.id = l.vehicle_id
    where la.price is not null
    group by v.trim
  `) as { trim: string; median: number }[];

  const median_asking_by_trim: Record<string, number> = {};
  for (const r of medians) median_asking_by_trim[r.trim] = Math.round(r.median);

  return json({
    active_vehicles,
    active_listings,
    vin_identification_rate: total ? Math.round((vinned / total) * 1000) / 1000 : 0,
    median_asking_by_trim,
  });
};
