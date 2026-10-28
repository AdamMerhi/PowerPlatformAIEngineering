{#
  dbt's default behaviour appends a custom schema as a suffix to the
  target schema (e.g. RAW_CLEAN). We want the schema config in
  dbt_project.yml to be used exactly as-is (CLEAN / CURATED) so models
  land in the same schemas the rest of this repo's Snowflake SQL uses.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
