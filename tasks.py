import ssl
from enum import Enum
from celery import Celery

from app import app

def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL'],
        broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
        redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE}
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery

class Pubs(Enum):
    Elsevier = "Elsevier"
    Wiley = "Wiley"
    SpringerNature = "Springer Nature"
    Sage = "SAGE"
    TaylorFrancis = "Taylor & Francis"

def update_apc(package_id):
    from app import get_db_cursor
    from psycopg2.extensions import AsIs

    find_q = 'select publisher from jump_account_package where package_id = %s'
    delete_q = 'delete from jump_apc_authorships where package_id = %s'
    insert_q = """
        insert into jump_apc_authorships (
            select * from jump_apc_authorships_view
            where package_id = %s and issn_l in 
            (select issn_l from journalsdb_computed rj where rj.publisher = %s))
    """
    make_temp_table = """
        select * into temp table %s from jump_apc_authorships_view
            where package_id = %s and issn_l in
            (select issn_l from journalsdb_computed rj where rj.publisher = %s)
    """
    insert_from_temp_table = """
        insert into jump_apc_authorships (select * from %s)
    """
    temp_table_name = 'apc_temp_' + package_id.replace('-', '_').lower()
    
    with get_db_cursor() as cursor:
        cursor.execute(find_q, (package_id,))
        row = cursor.fetchone()

    if row:
        with get_db_cursor() as cursor:
            cursor.execute(delete_q, (package_id,))

        # with get_db_cursor() as cursor:
        #     cursor.execute(insert_q, (package_id, Pubs[row['publisher']].value,))

        with get_db_cursor() as cursor:
            # print(cursor.mogrify(make_temp_table, (AsIs(temp_table_name), package_id, 'Elsevier',)))
            # print(cursor.mogrify(make_temp_table, (AsIs(temp_table_name), package_id, Pubs[row['publisher']].value,)))
            cursor.execute(make_temp_table, (AsIs(temp_table_name), package_id, Pubs[row['publisher']].value,))

        with get_db_cursor() as cursor:
            # print(cursor.mogrify(insert_from_temp_table, (AsIs(temp_table_name),)))
            cursor.execute(insert_from_temp_table, (AsIs(temp_table_name),))

        # cleanup temporary table
        with get_db_cursor() as cursor:
            cursor.execute('drop table %s', (AsIs(temp_table_name),))

celery = make_celery(app)

@celery.task(autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 3})
def update_apc_authships(package_id):
    update_apc(package_id)
    return f"apc authorships updated for {package_id}"
