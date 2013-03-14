-- The contents of this file are subject to the Common Public Attribution
-- License Version 1.0. (the "License"); you may not use this file except in
-- compliance with the License. You may obtain a copy of the License at
-- http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
-- License Version 1.1, but Sections 14 and 15 have been added to cover use of
-- software over a computer network and provide for limited attribution for the
-- Original Developer. In addition, Exhibit A has been modified to be
-- consistent with Exhibit B.
--
-- Software distributed under the License is distributed on an "AS IS" basis,
-- WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
-- the specific language governing rights and limitations under the License.
--
-- The Original Code is reddit.
--
-- The Original Developer is the Initial Developer.  The Initial Developer of
-- the Original Code is reddit Inc.
--
-- All portions of the code written by reddit are Copyright (c) 2006-2013
-- reddit Inc. All Rights Reserved.
-------------------------------------------------------------------------------

create or replace function hot(ups integer, downs integer, date timestamp with time zone) returns numeric as $$
    select round(cast(log(greatest(abs($1 - $2), 1)) + sign($1 - $2) * (date_part('epoch', $3) - 1134028003) / 45000.0 as numeric), 7)
$$ language sql immutable;

create or replace function score(ups integer, downs integer) returns integer as $$
    select $1 - $2
$$ language sql immutable;

create or replace function controversy(ups integer, downs integer) returns float as $$
    select cast(($1 + $2) as float)/(abs($1 - $2)+1)
$$ language sql immutable;

create or replace function ip_network(ip text) returns text as $$
    select substring($1 from E'[\\d]+\.[\\d]+\.[\\d]+')
$$ language sql immutable;

create or replace function base_url(url text) returns text as $$
    select substring($1 from E'(?i)(?:.+?://)?(?:www[\\d]*\\.)?([^#]*[^#/])/?')
$$ language sql immutable;

create or replace function domain(url text) returns text as $$
    select substring($1 from E'(?i)(?:.+?://)?(?:www[\\d]*\\.)?([^#/]*)/?')
$$ language sql immutable;

create view active as
    select pg_stat_activity.procpid, (now() - pg_stat_activity.query_start) as t, pg_stat_activity.current_query from pg_stat_activity where (pg_stat_activity.current_query <> '<IDLE>'::text) order by (now() - pg_stat_activity.query_start);
