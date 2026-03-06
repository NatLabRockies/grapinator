import graphene
import os
from os import path
from datetime import datetime
from crypto_config import cryptoconfigparser
from sqlalchemy.orm import (
    scoped_session
    ,sessionmaker
    ,relationship
    ,synonym
)
from sqlalchemy import (
    Column
    ,BigInteger
    ,Boolean
    ,Date
    ,DateTime
    ,Enum
    ,Float
    ,Integer
    ,Interval
    ,LargeBinary
    ,Numeric
    ,PickleType
    ,SmallInteger
    ,String
    ,Text
    ,Time
    ,Unicode
    ,UnicodeText
    )

class Settings(object):
    WSGI_SOCKET_HOST = None
    WSGI_SOCKET_PORT = None
    WSGI_SSL_CERT = None
    WSGI_SSL_PRIVKEY = None
    CORS_ENABLE = None
    CORS_EXPOSE_ORIGINS = None
    CORS_ALLOW_METHODS = None
    CORS_HEADER_MAX_AGE = None
    CORS_ALLOW_HEADERS = None
    CORS_EXPOSE_HEADERS = None
    CORS_SEND_WILDCARD = None
    CORS_SUPPORTS_CREDENTIALS = None
    HTTP_HEADERS_XFRAME = None
    HTTP_HEADERS_XSS_PROTECTION = None
    HTTP_HEADER_CACHE_CONTROL = None
    APP_VERSION = None
    GQL_SCHEMA = None
    FLASK_SERVER_NAME = None
    FLASK_DEBUG = None  
    FLASK_API_ENDPOINT = None
    DB_USER = None
    DB_PASSWORD = None
    DB_CONNECT = None
    DB_TYPE = None
    SQLALCHEMY_TRACK_MODIFICATIONS = None
    
    def __init__(self, **kwargs):
        config_file = kwargs.pop('config_file', None)
        if config_file != None:
            self.config_file = config_file
        else:
            raise RuntimeError('Could not parse config_file.')
        
        # CryptoConfigParser gets crypt_key from environment
        try:
            key = os.environ['GQLAPI_CRYPT_KEY']
        except KeyError as err:
            raise RuntimeError(f"Could not get env key: {err}")

        try:
            # load config file
            cwd = path.abspath(path.dirname(__file__))
            properties = cryptoconfigparser.CryptoConfigParser(crypt_key=key)
            properties_file = cwd + self.config_file
            properties.read(properties_file)

            # load APP section
            self.APP_VERSION = properties.get('APP', 'VERSION')
            
            # load WSGI section
            self.WSGI_SOCKET_HOST = properties.get('WSGI', 'WSGI_SOCKET_HOST')
            self.WSGI_SOCKET_PORT = properties.getint('WSGI', 'WSGI_SOCKET_PORT')
            if properties.has_option('WSGI', 'WSGI_SSL_CERT') and properties.has_option('WSGI', 'WSGI_SSL_PRIVKEY'):
                self.WSGI_SSL_CERT = properties.get('WSGI', 'WSGI_SSL_CERT')
                self.WSGI_SSL_PRIVKEY = properties.get('WSGI', 'WSGI_SSL_PRIVKEY')

            # load CORS
            self.CORS_ENABLE = properties.getboolean('CORS', 'CORS_ENABLE')
            self.CORS_EXPOSE_ORIGINS = properties.get('CORS', 'CORS_EXPOSE_ORIGINS')
            self.CORS_ALLOW_METHODS = properties.get('CORS', 'CORS_ALLOW_METHODS')
            self.CORS_HEADER_MAX_AGE = properties.get('CORS', 'CORS_HEADER_MAX_AGE')
            self.CORS_ALLOW_HEADERS = properties.get('CORS', 'CORS_ALLOW_HEADERS')
            self.CORS_EXPOSE_HEADERS = properties.get('CORS', 'CORS_EXPOSE_HEADERS')
            self.CORS_SEND_WILDCARD = properties.getboolean('CORS', 'CORS_SEND_WILDCARD')
            self.CORS_SUPPORTS_CREDENTIALS = properties.getboolean('CORS', 'CORS_SUPPORTS_CREDENTIALS')

            # load HTTP_HEADERS
            self.HTTP_HEADERS_XFRAME = properties.get('HTTP_HEADERS', 'HTTP_HEADERS_XFRAME')
            self.HTTP_HEADERS_XSS_PROTECTION = properties.get('HTTP_HEADERS', 'HTTP_HEADERS_XSS_PROTECTION')
            self.HTTP_HEADER_CACHE_CONTROL = properties.get('HTTP_HEADERS', 'HTTP_HEADER_CACHE_CONTROL')

            # load FLASK section
            self.FLASK_SERVER_NAME = properties.get('FLASK', 'FLASK_SERVER_NAME')
            self.FLASK_API_ENDPOINT = properties.get('FLASK', 'FLASK_API_ENDPOINT')
            self.FLASK_DEBUG = properties.getboolean('FLASK', 'FLASK_DEBUG')

            # load SQLALCHEMY section
            self.DB_TYPE = properties.get('SQLALCHEMY', 'DB_TYPE')  
            if properties.has_option('SQLALCHEMY', 'DB_USER'): 
                self.DB_USER = properties.get('SQLALCHEMY', 'DB_USER')
            if properties.has_option('SQLALCHEMY', 'DB_PASSWORD'): 
                self.DB_PASSWORD = properties.get('SQLALCHEMY', 'DB_PASSWORD')
            self.DB_CONNECT = properties.get('SQLALCHEMY', 'DB_CONNECT')
            if 'sqlite' in self.DB_TYPE:
                self.SQLALCHEMY_DATABASE_URI = f"{self.DB_TYPE}://{self.DB_CONNECT}"
            else:
                self.SQLALCHEMY_DATABASE_URI = f"{self.DB_TYPE}://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_CONNECT}"
            
            self.SQLALCHEMY_TRACK_MODIFICATIONS = properties.getboolean('SQLALCHEMY', 'SQLALCHEMY_TRACK_MODIFICATIONS')

            # load GRAPHENE section
            self.GQL_SCHEMA = properties.get('GRAPHENE', 'GQL_SCHEMA')

            # set oracle environment stuff for SQLAlchemy
            if properties.has_option('SQLALCHEMY', 'ORCL_NLS_LANG'):
                os.environ['NLS_LANG'] = properties.get('SQLALCHEMY', 'ORCL_NLS_LANG')
            if properties.has_option('SQLALCHEMY', 'ORCL_NLS_DATE_FORMAT'):
                os.environ['NLS_DATE_FORMAT'] = properties.get('SQLALCHEMY', 'ORCL_NLS_DATE_FORMAT')
            
        except cryptoconfigparser.ParsingError as err:
            raise RuntimeError(f"Could not parse: {err}")

class SchemaSettings(object):
    def __init__(self, *args, **kwargs):
        file = kwargs.pop('schema_file', None)
        if file != None:
            # load file
            cwd = path.abspath(path.dirname(__file__))
            self._schema_dict = self._loadSchemaDict(cwd + file)

            self._db_classes = self._make_db_classes()
            self._gql_classes = self._make_gql_classes()
        else:
            raise TypeError("schema_file arg not set!")


    def _loadSchemaDict(self, file_name):
        s = open(file_name, 'r').read()
        schema_dict = eval(s)
        return schema_dict

    def _make_db_classes(self):
        db_classes = []
        for row in self._schema_dict:
            db_class_cols = [{
                'name':r['gql_col_name']
                ,'db_col_name':r['db_col_name']
                ,'db_type':r['db_type']
                } for r in row['FIELDS'] if r['db_col_name']]
            db_class_relation = [{
                'name':r['rel_name']
                ,'class_name':r['rel_class_name']
                ,'arguments':r['rel_arguments']
                } for r in row['RELATIONSHIPS']]
            db_class = {
                'db_class': row['DB_CLASS_NAME']
                ,'db_table': row['DB_TABLE_NAME']
                ,'db_pk': row['DB_TABLE_PK']
                ,'db_columns': db_class_cols
                ,'db_relationships': db_class_relation
                }
            db_classes.append(db_class)
        return db_classes

    def _make_gql_classes(self):
        gql_classes = []
        for row in self._schema_dict:
            gql_class_cols = [{
                'name':r['gql_col_name']
                ,'type':r['gql_type']
                ,'desc':r['gql_description']
                ,'type_args': r['gql_of_type'] if 'gql_of_type' in r else None
                ,'isqueryable': r['gql_isqueryable'] if 'gql_isqueryable' in r else True
                ,'ishidden': r['gql_ishidden'] if 'gql_ishidden' in r else False
                ,'isresolver': r['gql_isresolver'] if 'gql_isresolver' in r else False
                ,'resolver_func':r['gql_resolver_func'] if 'gql_resolver_func' in r else None
                } for r in row['FIELDS']]
            gql_class = {
                'gql_class': row['GQL_CLASS_NAME']
                ,'gql_conn_query_name': row['GQL_CONN_QUERY_NAME']
                ,'gql_db_class': row['DB_CLASS_NAME']
                ,'gql_columns': gql_class_cols
                ,'gql_db_default_sort_col': row['DB_DEFAULT_SORT_COL']
                }
            gql_classes.append(gql_class)
        return gql_classes

    def get_db_classes(self):
        return self._db_classes

    def get_gql_classes(self):
        return self._gql_classes
