-- "Mac Apps Report"
-- Internal-1P only https://app.kolide.com/4918/reporting/queries/2080

-- Reporting DB query to retrieve all mac_apps installed across the fleet,
-- filtering out a list of "approved apps" such as 1Password and anything
-- built by either Apple or Google using their bundle_identifier.

-- The final report contains an ordered list of "unapproved" apps with a 
-- JSON formatted device table containing the device name, serial and admin URL.

WITH device_info AS (
    SELECT
        id as device_id,
        name,
        serial,
        k2_url,
        id || ' (' || name || ')' as device_name
    FROM
        devices
),

apps AS (
    SELECT 
        *
    FROM 
        mac_apps
    WHERE 
        1=1
        AND path LIKE '/Applications%'
        AND name NOT LIKE '1Password%.app'
        AND bundle_identifier NOT LIKE 'com.apple.%'
        AND bundle_identifier NOT LIKE 'com.google.%'
)

SELECT
    a.name,
    a.bundle_identifier,
    COUNT(*) as count,
    JSON_AGG(
        JSON_BUILD_OBJECT(
            'device_name', d.device_name,
            'device_serial', d.serial,
            'url', d.k2_url
        ) ORDER BY d.device_name
    ) as device_table
FROM apps as a
JOIN device_info as d on d.device_id = a.device_id
GROUP BY 1, 2
ORDER BY count DESC