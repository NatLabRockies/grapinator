# Demo GraphQL Queries — Northwind Database

The playground GraphiQL interface is available at [http://localhost:8443/northwind/gql](http://localhost:8443/northwind/gql) once the app is running.

---

## Return all employees sorted by last name

```graphql
{
  employees(sort_by: "last_name" sort_dir: "asc") {
    edges {
      node {
        employee_id
        first_name
        last_name
        title
        title_of_courtesy
        hire_date
        city
        country
      }
    }
  }
}
```

---

## Return a single employee by ID with their assigned territories

```graphql
{
  employees(employee_id: 1) {
    edges {
      node {
        employee_id
        first_name
        last_name
        title
        notes

        employee_territories {
          territory_id

          territories {
            territory_description
            region_id

            region {
              region_description
            }
          }
        }
      }
    }
  }
}
```

---

## Return all customers in a specific country sorted by company name

```graphql
{
  customers(country: "USA" sort_by: "company_name" sort_dir: "asc") {
    edges {
      node {
        customer_id
        company_name
        contact_name
        contact_title
        city
        region
        phone
        fax
      }
    }
  }
}
```

---

## Return all orders for a specific customer with employee and shipper details

```graphql
{
  orders(customer_id: "ALFKI" sort_by: "order_date" sort_dir: "desc") {
    edges {
      node {
        order_id
        order_date
        required_date
        shipped_date
        freight
        ship_name
        ship_city
        ship_country

        employee {
          first_name
          last_name
          title
        }

        customer {
          company_name
          contact_name
          phone
        }

        shipper {
          company_name
          phone
        }
      }
    }
  }
}
```

---

## Return order line items with product details for a specific order

```graphql
{
  order_details(order_id: 10248) {
    edges {
      node {
        order_id
        unit_price
        quantity
        discount

        product {
          product_name
          quantity_per_unit
          units_in_stock
          discontinued

          category {
            category_name
            description
          }

          supplier {
            company_name
            country
          }
        }
      }
    }
  }
}
```

---

## Return all products in a specific category sorted by product name

```graphql
{
  products(category_id: 1 sort_by: "product_name" sort_dir: "asc") {
    edges {
      node {
        product_id
        product_name
        quantity_per_unit
        unit_price
        units_in_stock
        reorder_level
        discontinued

        supplier {
          company_name
          contact_name
          country
          phone
        }

        category {
          category_name
          description
        }
      }
    }
  }
}
```

---

## Return all product categories

```graphql
{
  categories(sort_by: "category_name" sort_dir: "asc") {
    edges {
      node {
        category_id
        category_name
        description
      }
    }
  }
}
```

---

## Return all suppliers in a specific country

```graphql
{
  suppliers(country: "USA" sort_by: "company_name" sort_dir: "asc") {
    edges {
      node {
        supplier_id
        company_name
        contact_name
        contact_title
        city
        region
        country
        phone
        fax
        home_page
      }
    }
  }
}
```

---

## Return all shippers

```graphql
{
  shippers(sort_by: "company_name" sort_dir: "asc") {
    edges {
      node {
        shipper_id
        company_name
        phone
      }
    }
  }
}
```

---

## Return all regions with their territories

```graphql
{
  regions(sort_by: "region_id" sort_dir: "asc") {
    edges {
      node {
        region_id
        region_description

        territories {
          territory_id
          territory_description
        }
      }
    }
  }
}
```

---

## Return all orders placed in a date range >= 1997-01-01 sorted by order date

```graphql
{
  orders(
    order_date: "1997-01-01"
    matches: "gt"
    sort_by: "order_date"
    sort_dir: "asc"
  ) {
    edges {
      node {
        order_id
        order_date
        shipped_date
        freight
        ship_country

        customer {
          company_name
          country
        }

        employee {
          first_name
          last_name
        }
      }
    }
  }
}
```

---

## Filtering with `where` (v2.2.0+)

The queries below use the typed `where` argument. See
[graphiql_user_guide.md](graphiql_user_guide.md#filtering-with-where) for the
full operator list and null/list semantics.

### Orders in a date range shipped to Germany or France

```graphql
{
  orders(
    where: {
      order_date: { gte: "2017-01-01T00:00:00", lt: "2017-02-01T00:00:00" }
      ship_country: { in: ["Germany", "France"] }
    }
    sort_by: "order_date"
  ) {
    edges {
      node {
        order_id
        order_date
        ship_country
      }
    }
  }
}
```

### Two employees by ID

```graphql
{
  employees(where: { employee_id: { in: [1, 5] } }) {
    edges {
      node {
        employee_id
        first_name
        last_name
      }
    }
  }
}
```

### German customers in Berlin, or whose company name starts with "Ma"

```graphql
{
  customers(
    where: {
      or: [
        { city: { eq: "Berlin" }, country: { eq: "Germany" } }
        { company_name: { startsWith: "ma" } }
      ]
    }
    sort_by: "company_name"
  ) {
    edges {
      node {
        customer_id
        company_name
        region
        country
      }
    }
  }
}
```

### Products under $10 that are not in category 1

```graphql
{
  products(
    where: {
      unit_price: { lt: 10 }
      not: { category_id: { eq: 1 } }
    }
    sort_by: "unit_price"
  ) {
    edges {
      node {
        product_name
        unit_price
        category_id
      }
    }
  }
}
```

### Using variables

```graphql
query EmployeesByCity($filter: EmployeesFilter) {
  employees(where: $filter, sort_by: "last_name") {
    edges {
      node {
        first_name
        last_name
        city
      }
    }
  }
}
```

Variables:

```json
{ "filter": { "city": { "in": ["London", "Seattle"] }, "employee_id": { "gt": 3 } } }
```

### Employees with another manager, including those with no manager

`ne` does not match SQL NULL. Include a separate `isNull` branch when missing
values should also match:

```graphql
query OtherOrMissingManager {
  employees(
    where: { or: [{ reports_to: { ne: 2 } }, { reports_to: { isNull: true } }] }
    sort_by: "employee_id"
  ) {
    edges { node { employee_id last_name reports_to } }
  }
}
```

### Available products within an inclusive price range

Each column condition and each operator on a column must match. Use `notIn`
for an exclusion list:

```graphql
query AvailableProductsInRange {
  products(
    where: {
      unit_price: { gte: 10, lte: 30 }
      units_in_stock: { gt: 0 }
      category_id: { notIn: [1, 2] }
    }
    sort_by: "product_id"
  ) {
    edges { node { product_id product_name unit_price units_in_stock category_id } }
  }
}
```

### Nested AND, OR, and NOT with case-insensitive text matching

```graphql
query NestedNameSearch {
  employees(
    where: {
      and: [
        { or: [{ last_name: { contains: "LL" } }, { last_name: { endsWith: "ING" } }] }
        { not: { city: { startsWith: "Lon" } } }
        { employee_id: { notIn: [1, 3] } }
      ]
    }
    sort_by: "employee_id"
  ) {
    edges { node { employee_id last_name city } }
  }
}
```

See the [worked filter examples](graphiql_user_guide.md#worked-filter-examples)
for scalar formats, half-open date ranges, literal wildcard characters, and
additional combinations. `eq: null`, null list members, and operators belonging
to another scalar type are rejected; use `isNull` for missing values. These
filters cannot traverse relationships or bypass role/row policies.

---

## Pagination with and without a server cap

These examples assume the unmodified Northwind sample and access to all nine
employees. Restart the service after editing `[GRAPHENE]` in the active INI.
Keep sorting, filters, and authorization unchanged between pages, and copy
returned cursors without decoding or constructing them.

**Unset:** omit or comment out `MAX_PAGE_SIZE`. A query without `first` / `last`
returns all matching rows, and `first: 50` returns up to 50.

**Set:** add `MAX_PAGE_SIZE = 3`. A query without sizes defaults to three rows;
`first: 50` and `last: 50` are clamped to three. `first: 2` still returns two.
This is not an error, so do not assume fewer than 50 rows means the last page.

### Unpaged request under either configuration

```graphql
query DefaultEmployeePage {
  employees(sort_by: "employee_id") {
    edges { node { employee_id last_name } }
    pageInfo { hasNextPage endCursor }
  }
}
```

Unset: IDs `[1, 2, 3, 4, 5, 6, 7, 8, 9]`, `hasNextPage: false`.
Set to three: IDs `[1, 2, 3]`, `hasNextPage: true`; continue with `after`.

### Forward pages with a where filter

```graphql
query LondonEmployeePages($after: String) {
  employees(
    where: { city: { eq: "London" } }
    first: 50
    after: $after
    sort_by: "employee_id"
  ) {
    edges { node { employee_id last_name city } }
    pageInfo { hasNextPage endCursor }
  }
}
```

First variables: `{ "after": null }`. When the cap is unset this returns
`[5, 6, 7, 9]` with `hasNextPage: false`. With a cap of three, the first response
contains `[5, 6, 7]` and `hasNextPage: true`. Run again with
`{ "after": "<returned endCursor>" }`, replacing the placeholder with that
cursor: the next page contains `[9]` and `hasNextPage: false`.

### Backward pages

```graphql
query EmployeePagesBackward($before: String) {
  employees(last: 50, before: $before, sort_by: "employee_id") {
    edges { node { employee_id last_name } }
    pageInfo { hasPreviousPage startCursor }
  }
}
```

First variables: `{ "before": null }`. Unset: all nine IDs, no previous page.
Set to three: `[7, 8, 9]`, then `[4, 5, 6]`, then `[1, 2, 3]`. For each earlier
page, replace `before` with the preceding response's `startCursor`; stop when
`hasPreviousPage` is false. Each page remains ascending by employee ID.

For small explicit pages with no cap, replace `first: 50` or `last: 50` with
`3` in these queries and use the same cursor workflow. See the
[configuration examples](grapinator_ini.md#pagination-with-the-cap-unset-or-set)
and [complete pagination guide](graphiql_user_guide.md#pagination).
