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