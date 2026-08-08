import { getSql, json, type Env } from "../_shared";

// GET /api/listings — active listings with their latest observed price/mileage.
export const onRequestGet: PagesFunction<Env> = async ({ env }) => {
  const sql = getSql(env);
  const rows = await sql`
    with latest as (
      select distinct on (o.listing_id) o.listing_id, o.price, o.mileage
      from listing_observations o
      order by o.listing_id, o.observed_at desc
    )
    select l.id            as listing_id,
           v.id            as vehicle_id,
           v.vin, v.year, v.trim, v.transmission,
           la.price::float as price,
           la.mileage      as mileage,
           s.key           as source,
           l.url,
           l.first_seen_at as first_seen,
           l.last_seen_at  as last_seen
    from listings l
    join vehicles v on v.id = l.vehicle_id
    join sources  s on s.id = l.source_id
    left join latest la on la.listing_id = l.id
    where l.status = 'active'
    order by l.last_seen_at desc
  `;
  return json(rows);
};
