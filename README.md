<table border="0">
<tr>
<td><img src="GraphinatorLogoTrans.png"></td>
<td>
<h1>Grapinator</h1>
<h2>Dynamic GraphQL API Creator for Python</h2>
</td>
</tr>
</table>

## Introduction
Grapinator is a dynamic api generator based on the [Graphene](http://graphene-python.org) library for building GraphQL query services.  All you have to do to get a fully fuctional GraphQL service up and running is to configure a few setup files!  

## Key Features
- **No coding required:** Utilizes Python metaprogramming so no additional coding is required to implement new GraphQL services!
- **Built with Flask-SQLAlchemy:** Code based on the [SQLAlchemy + Flask Tutorial](http://docs.graphene-python.org/projects/sqlalchemy/en/latest/tutorial/) examples.
- **Runtime configuration:** Runtime configuration is managaged using the [grapinator.ini](grapinator/resources/grapinator.ini) file. 
- **Flexable GraphQL schema definition:** All Graphene and database information is provided by a [Python dictionary](grapinator/resources/schema.dct) that you change for your needs. Please review the [schema documentation](docs/schema_docs.md).
- **Additional query logic:** More robust query logic has been added giving the api consumer more options to query for specific data.

## Licensing
This project is licensed under the [BSD 3-clause](License.txt) license.

## Contributing
Allthough I use this code in production at my company, I consider it alpha code.  If you have any ideas, just open an issue and tell me what you think, how it may be improved, bugs you may find, etc.

## Getting Started

### Demo 

A [sqlite database](db/README.md) has been provided using the classic demo Northwind db. A grapinator [schema definition file](grapinator/resources/northwind_schema.dct) for this demo has been configured for this database as a playground and 
will be invoked during application startup via the default [grapinator.ini](grapinator/resources/grapinator.ini) file.

Follow the build instructions below to get the playground up and running.  Once app.py is started, you will have a web service up and running on localhost:8443.  You may use the built in [GraphiQL web page](http://localhost:8443/northwind/gql) to try some queries.

### Development setup
#### Setup OSX/Linux
```
python -m venv venv
source venv/bin/activate
(venv) $ export $(cat .env)
(venv) $ pip install -e .
(venv) $ python grapinator/app.py
```

#### Setup using conda
```
conda create -n grapinator python
conda activate grapinator
(grapinator) $ export $(cat .env)
(grapinator) $ pip install -e .
(grapinator) $ python grapinator/app.py
```

#### Running unit tests from the command line
Unit tests are located in the 'tests' directory.
```
GQLAPI_CRYPT_KEY=testkey python -m unittest discover tests/ -v
```
