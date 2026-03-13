# GraphQL Integration Test Queries - Northwind Database

This file contains comprehensive GraphQL queries for integration testing of the Northwind database GraphQL API. These queries are designed to test various scenarios including basic operations, relationships, filtering, sorting, pagination, and edge cases.

---

## Basic Entity Retrieval Tests

### 1. Get All Employees - Basic Fields
Test basic employee retrieval with essential fields.
```graphql
query GetAllEmployees {
  employees {
    edges {
      node {
        employee_id
        first_name
        last_name
        title
        hire_date
        city
        country
      }
    }
  }
}
```

### 2. Get Single Employee by ID
Test single entity retrieval and verify specific employee exists.
```graphql
query GetEmployeeById {
  employees(employee_id: 1) {
    edges {
      node {
        employee_id
        first_name
        last_name
        title
        title_of_courtesy
        birth_date
        hire_date
        address
        city
        region
        postal_code
        country
        home_phone
        extension
        notes
        reports_to
      }
    }
  }
}
```

### 3. Get All Products - Full Fields
Test product retrieval with all available fields.
```graphql
query GetAllProducts {
  products {
    edges {
      node {
        product_id
        product_name
        supplier_id
        category_id
        quantity_per_unit
        unit_price
        units_in_stock
        reorder_level
        discontinued
      }
    }
  }
}
```

### 4. Get All Categories
Test category retrieval for reference data.
```graphql
query GetAllCategories {
  categories {
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

## Relationship Tests

### 5. Employee with Territories (One-to-Many)
Test employee to territories relationship via junction table.
```graphql
query EmployeeWithTerritories {
  employees(employee_id: 1) {
    edges {
      node {
        employee_id
        first_name
        last_name
        
        employee_territories {
          territory_id
          
          territories {
            territory_id
            territory_description
            region_id
            
            region {
              region_id
              region_description
            }
          }
        }
      }
    }
  }
}
```

### 6. Product with Category and Supplier (Many-to-One)
Test product relationships to both category and supplier.
```graphql
query ProductWithCategoryAndSupplier {
  products(product_id: 1) {
    edges {
      node {
        product_id
        product_name
        unit_price
        units_in_stock
        discontinued
        
        category {
          category_id
          category_name
          description
        }
        
        supplier {
          supplier_id
          company_name
          contact_name
          contact_title
          city
          country
          phone
        }
      }
    }
  }
}
```

### 7. Order with Complete Details (Complex Relationships)
Test order with customer, employee, shipper, and order details.
```graphql
query CompleteOrderDetails {
  orders(order_id: 10248) {
    edges {
      node {
        order_id
        order_date
        required_date
        shipped_date
        freight
        ship_name
        ship_address
        ship_city
        ship_region
        ship_postal_code
        ship_country
        
        customer {
          customer_id
          company_name
          contact_name
          contact_title
          phone
          fax
          city
          country
        }
        
        employee {
          employee_id
          first_name
          last_name
          title
        }
        
        shipper {
          shipper_id
          company_name
          phone
        }
      }
    }
  }
}
```

### 8. Order Details with Product Information
Test order line items with nested product, category, and supplier data.
```graphql
query OrderDetailsWithProducts {
  order_details(order_id: 10248) {
    edges {
      node {
        order_id
        product_id
        unit_price
        quantity
        discount
        
        product {
          product_id
          product_name
          quantity_per_unit
          units_in_stock
          discontinued
          
          category {
            category_id
            category_name
            description
          }
          
          supplier {
            supplier_id
            company_name
            contact_name
            country
            phone
          }
        }
      }
    }
  }
}
```

---

## Filtering Tests

### 9. Filter Customers by Country
Test exact match filtering.
```graphql
query CustomersByCountry {
  customers(country: "USA") {
    edges {
      node {
        customer_id
        company_name
        contact_name
        city
        region
        country
        phone
      }
    }
  }
}
```

### 10. Filter Employees by City (Multiple Results)
Test filtering with multiple expected results.
```graphql
query EmployeesByCity {
  employees(city: "Seattle") {
    edges {
      node {
        employee_id
        first_name
        last_name
        title
        city
        hire_date
      }
    }
  }
}
```

### 11. Filter Products by Category
Test filtering via foreign key relationship.
```graphql
query ProductsByCategory {
  products(category_id: 1) {
    edges {
      node {
        product_id
        product_name
        category_id
        unit_price
        units_in_stock
        discontinued
        
        category {
          category_name
          description
        }
      }
    }
  }
}
```

### 12. Find Discontinued Products
Test filtering by boolean-like field.
```graphql
query DiscontinuedProducts {
  products(discontinued: "1") {
    edges {
      node {
        product_id
        product_name
        unit_price
        units_in_stock
        discontinued
        
        category {
          category_name
        }
      }
    }
  }
}
```

---

## Sorting Tests

### 13. Employees Sorted by Hire Date (Ascending)
Test date sorting in ascending order.
```graphql
query EmployeesByHireDate {
  employees(sort_by: "hire_date", sort_dir: "asc") {
    edges {
      node {
        employee_id
        first_name
        last_name
        title
        hire_date
      }
    }
  }
}
```

### 14. Products Sorted by Price (Descending)
Test numeric sorting in descending order.
```graphql
query ProductsByPriceDesc {
  products(sort_by: "unit_price", sort_dir: "desc") {
    edges {
      node {
        product_id
        product_name
        unit_price
        units_in_stock
        
        category {
          category_name
        }
      }
    }
  }
}
```

### 15. Customers Sorted by Company Name
Test string sorting (default ascending).
```graphql
query CustomersByCompanyName {
  customers(sort_by: "company_name", sort_dir: "asc") {
    edges {
      node {
        customer_id
        company_name
        contact_name
        city
        country
      }
    }
  }
}
```

---

## Combined Filtering and Sorting Tests

### 16. US Customers Sorted by State and City
Test multiple field filtering and sorting.
```graphql
query USCustomersByLocation {
  customers(country: "USA", sort_by: "city", sort_dir: "asc") {
    edges {
      node {
        customer_id
        company_name
        contact_name
        city
        region
        postal_code
        country
      }
    }
  }
}
```

### 17. Active Products in Beverages Category Sorted by Name
Test category filtering with sorting.
```graphql
query BeverageProductsSorted {
  products(category_id: 1, discontinued: "0", sort_by: "product_name", sort_dir: "asc") {
    edges {
      node {
        product_id
        product_name
        unit_price
        units_in_stock
        discontinued
        
        category {
          category_name
        }
      }
    }
  }
}
```

---

## Advanced Matching Tests

### 18. Products with Name Pattern Matching (Contains)
Test partial string matching capability.
```graphql
query ProductsContainingCheese {
  products(product_name: "Cheese", matches: "contains") {
    edges {
      node {
        product_id
        product_name
        category_id
        unit_price
        
        category {
          category_name
        }
      }
    }
  }
}
```

### 19. Customers with Name Starting With Pattern
Test startswith matching.
```graphql
query CustomersStartingWithA {
  customers(company_name: "A", matches: "startswith") {
    edges {
      node {
        customer_id
        company_name
        contact_name
        city
        country
      }
    }
  }
}
```

### 20. Expensive Products (Greater Than)
Test numeric comparison filtering.
```graphql
query ExpensiveProducts {
  products(unit_price: 50, matches: "gt") {
    edges {
      node {
        product_id
        product_name
        unit_price
        
        category {
          category_name
        }
        
        supplier {
          company_name
          country
        }
      }
    }
  }
}
```

---

## Date Range Tests

### 21. Recent Orders (Date Filtering)
Test date-based filtering for recent orders.
```graphql
query OrdersAfter1996 {
  orders(order_date: "1996-01-01", matches: "gte") {
    edges {
      node {
        order_id
        customer_id
        order_date
        required_date
        shipped_date
        freight
        
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

### 22. Orders in Specific Date Range
Test filtering orders within a specific year.
```graphql
query Orders1997 {
  orders(order_date: "1997-01-01", matches: "gte", sort_by: "order_date", sort_dir: "asc") {
    edges {
      node {
        order_id
        order_date
        shipped_date
        
        customer {
          company_name
          country
        }
      }
    }
  }
}
```

---

## Aggregation and Business Logic Tests

### 23. High-Value Orders (Complex Query)
Test orders with high freight values and complete details.
```graphql
query HighValueOrders {
  orders(freight: 100, matches: "gt", sort_by: "freight", sort_dir: "desc") {
    edges {
      node {
        order_id
        order_date
        freight
        ship_country
        
        customer {
          customer_id
          company_name
          country
        }
        
        employee {
          first_name
          last_name
          title
        }
      }
    }
  }
}
```

### 24. Products Low in Stock
Test inventory-related queries.
```graphql
query LowStockProducts {
  products(
    matches: "lte"
    units_in_stock: 10
    logic: "and"
    discontinued: "0"
    sort_by: "units_in_stock"
    sort_dir: "desc"
  ) {
    edges {
      node {
        product_id
        product_name
        units_in_stock
        reorder_level
        discontinued
        category {
          category_name
        }
        supplier {
          company_name
          contact_name
          phone
        }
      }
    }
  }
```

---

## Edge Cases and Error Handling

### 25. Non-Existent Employee ID
Test handling of invalid/non-existent IDs.
```graphql
query NonExistentEmployee {
  employees(employee_id: 99999) {
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

### 26. Empty Result Set
Test queries that should return no results.
```graphql
query NoResultsExpected {
  customers(country: "NonExistentCountry") {
    edges {
      node {
        customer_id
        company_name
        country
      }
    }
  }
}
```

### 27. All Regions (Reference Data)
Test complete reference data retrieval.
```graphql
query AllRegions {
  regions {
    edges {
      node {
        region_id
        region_description
      }
    }
  }
}
```

### 28. All Shippers (Small Table)
Test retrieval of complete small tables.
```graphql
query AllShippers {
  shippers {
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

## Performance and Large Data Tests

### 29. All Orders (Large Dataset)
Test performance with larger result sets.
```graphql
query AllOrders {
  orders {
    edges {
      node {
        order_id
        customer_id
        employee_id
        order_date
        shipped_date
        freight
        ship_country
      }
    }
  }
}
```

### 30. All Order Details (Largest Table)
Test performance with the largest table in the schema.
```graphql
query AllOrderDetails {
  order_details {
    edges {
      node {
        order_id
        product_id
        unit_price
        quantity
        discount
      }
    }
  }
}
```

---

## Multi-Level Relationship Tests

### 31. Complete Supply Chain View
Test deep nested relationships: Product -> Supplier, Category, and Orders.
```graphql
query SupplyChainView {
  products(product_id: 1) {
    edges {
      node {
        product_id
        product_name
        unit_price
        units_in_stock
        
        category {
          category_id
          category_name
          description
        }
        
        supplier {
          supplier_id
          company_name
          contact_name
          address
          city
          country
          phone
          home_page
        }
      }
    }
  }
}
```

### 32. Customer Order History Summary 
Test customer with their order history.
```graphql
query CustomerOrderHistory {
  customers(customer_id: "ALFKI") {
    edges {
      node {
        customer_id
        company_name
        contact_name
        city
        country
        phone
      }
    }
  }
}
```

---

## Validation Queries for Data Integrity

### 33. Orders Without Shipped Date
Test for incomplete orders (business rule validation).
```graphql
query UnshippedOrders {
  orders(shipped_date: null, sort_by: "order_date", sort_dir: "desc") {
    edges {
      node {
        order_id
        order_date
        required_date
        shipped_date
        
        customer {
          company_name
        }
      }
    }
  }
}
```

### 34. Products Without Category
Test for data integrity issues.
```graphql
query ProductsWithoutCategory {
  products(category_id: null) {
    edges {
      node {
        product_id
        product_name
        category_id
        discontinued
      }
    }
  }
}
```

---

## Test Execution Notes

### Expected Results Validation
- **Query 1**: Should return 9 employees (standard Northwind dataset)
- **Query 2**: Should return Nancy Davolio (employee_id: 1)
- **Query 4**: Should return 8 categories
- **Query 9**: Should return 13 US customers
- **Query 27**: Should return 4 regions

### Performance Benchmarks
- Single entity queries should complete in < 100ms
- Complex relationship queries should complete in < 500ms
- Large dataset queries (all orders) should complete in < 2s

### Error Handling Validation
- Query 25: Should return empty result set, not error
- Query 26: Should return empty edges array
- Invalid field names should return GraphQL schema errors

### Data Consistency Checks
- All foreign key references should resolve properly
- Date fields should be properly formatted
- Numeric calculations should be accurate
- Boolean fields should be consistent