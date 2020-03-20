import json
import os
import re
import tempfile
from re import sub

import boto3
import dateutil.parser
import shortuuid
import unicodecsv as csv
from sqlalchemy.sql import text

from app import db, logger
from excel import convert_spreadsheet_to_csv
from util import safe_commit


class PackageInput:
    @staticmethod
    def normalize_date(date_str):
        if date_str:
            try:
                return dateutil.parser.parse(date_str).isoformat()
            except Exception:
                raise ValueError(u"unrecognized datetime format")
        else:
            return None

    @staticmethod
    def normalize_year(year):
        if year:
            try:
                return dateutil.parser.parse(year).year
            except Exception:
                raise ValueError(u"unrecognized year format")
        else:
            return None

    @staticmethod
    def normalize_int(value):
        if value:
            try:
                value = sub(ur'[^\d]', '', value)
                return int(value)
            except Exception:
                raise ValueError(u"unrecognized integer format")
        else:
            return None

    @staticmethod
    def normalize_price(price):
        if price:
            try:
                decimal = u',' if re.search(ur'\.\d{3}', price) or re.search(ur',\d{2}$', price) else ur'\.'
                sub_pattern = ur'[^\d{}]'.format(decimal)
                price = sub(sub_pattern, '', price)
                price = sub(',', '.', price)
                return int(round(float(price)))
            except Exception:
                raise ValueError(u"unrecognized price format")
        else:
            return None

    @staticmethod
    def normalize_issn(issn):
        if issn:
            issn = sub(ur'[^\dFSX-]', '', issn)
            if re.search(ur'(?:FS|\d\d)\d\d-\d{3}(?:X|\d)', issn.strip().upper()):
                return issn.strip().upper()
            else:
                raise ValueError(u'invalid ISSN format')
        else:
            return None

    @classmethod
    def csv_columns(cls):
        raise NotImplementedError()

    @classmethod
    def translate_row(cls, row):
        return [row]

    @classmethod
    def ignore_row(cls, row):
        return False

    @classmethod
    def normalize_cell(cls, column_name, column_value):
        for canonical_name, spec in cls.csv_columns().items():
            for snippet in spec['name_snippets']:
                snippet = snippet.lower()
                column_name = column_name.strip().lower()
                exact_name = spec.get('exact_name', False)
                if (exact_name and snippet == column_name) or (not exact_name and snippet in column_name.lower()):
                    return {canonical_name: spec['normalize'](column_value)}

        return None

    @classmethod
    def _copy_to_s3(cls, package_id, filename):
        s3 = boto3.client('s3')
        bucket_name = 'jump-redshift-staging'
        object_name = '{}_{}_{}'.format(package_id, cls.__name__, shortuuid.uuid())
        s3.upload_file(filename, bucket_name, object_name)
        return 's3://{}/{}'.format(bucket_name, object_name)

    @classmethod
    def delete(cls, package_id):
        if package_id == 'BwfVyRm9':
            num_deleted = db.session.query(cls).filter(cls.package_id == package_id).delete()
            safe_commit(db)
            return u'Deleted {} {} rows for package {}.'.format(num_deleted, cls.__name__, package_id)
        else:
            num_rows = db.session.query(cls).filter(cls.package_id == package_id).count()
            return u'Simulated deleting {} {} rows for package {}.'.format(num_rows, cls.__name__,package_id)

    @classmethod
    def load(cls, package_id, file_name):
        if file_name.endswith(u'.xls') or file_name.endswith(u'.xlsx'):
            csv_file_name = convert_spreadsheet_to_csv(file_name, parsed=False)
            if csv_file_name is None:
                return False, u'{} could not be opened as a spreadsheet'.format(file_name)
            else:
                file_name = csv_file_name

        with open(file_name, 'r') as csv_file:
            dialect = csv.Sniffer().sniff(csv_file.readline())
            csv_file.seek(0)

            # skip to the first complete header row
            max_columns = 0
            header_index = None
            parsed_rows = []
            for line_no, line in enumerate(csv.reader(csv_file, dialect=dialect)):
                parsed_rows.append(line)

                if len(line) > max_columns and all(line):
                    max_columns = len(line)
                    header_index = line_no
                    logger.info(u'candidate header row: {}'.format(u', '.join(line)))

            if header_index is None:
                return False, u"Couldn't identify a header row in the file"

            row_dicts = [dict(zip(parsed_rows[header_index], x)) for x in parsed_rows[header_index+1:]]

            normalized_rows = []
            for row_no, row in enumerate(row_dicts):
                normalized_row = {}

                for column_name in row.keys():
                    try:
                        normalized_cell = cls.normalize_cell(column_name, row[column_name])
                        if normalized_cell:
                            normalized_row = dict(normalized_cell.items() + normalized_row.items())
                    except Exception as e:
                        return False, u'Error reading row {}: {} for {}'.format(
                            row_no + 1, e.message, row[column_name]
                        )

                if cls.ignore_row(normalized_row):
                    continue

                row_keys = sorted(normalized_row.keys())
                expected_keys = sorted([k for k, v in cls.csv_columns().items() if v.get('required', True)])

                if set(expected_keys).difference(set(row_keys)):
                    return False, u'Missing expected columns. Expected {} but got {}.'.format(
                        ', '.join(expected_keys),
                        ', '.join(row.keys())
                    )

                normalized_rows.extend(cls.translate_row(normalized_row))

        for row in normalized_rows:
            row.update({'package_id': package_id})
            logger.info(u'normalized row: {}'.format(json.dumps(row)))

        if package_id == 'BwfVyRm9':
            db.session.query(cls).filter(cls.package_id == package_id).delete()

            if normalized_rows:
                sorted_fields = sorted(normalized_rows[0].keys())
                normalized_csv_filename = tempfile.mkstemp()[1]
                with open(normalized_csv_filename, 'w') as normalized_csv_file:
                    writer = csv.DictWriter(normalized_csv_file, delimiter=',', encoding='utf-8', fieldnames=sorted_fields)
                    for row in normalized_rows:
                        writer.writerow(row)

                s3_object = cls._copy_to_s3(package_id, normalized_csv_filename)

                copy_cmd = text('''
                    copy {table}({fields}) from '{s3_object}'
                    credentials :creds format as csv
                    timeformat 'auto';
                '''.format(
                    table=cls.__tablename__,
                    fields=', '.join(sorted_fields),
                    s3_object=s3_object,
                ))

                aws_creds = 'aws_access_key_id={aws_key};aws_secret_access_key={aws_secret}'.format(
                    aws_key=os.getenv('AWS_ACCESS_KEY_ID'),
                    aws_secret=os.getenv('AWS_SECRET_ACCESS_KEY')
                )

                db.session.execute(copy_cmd.bindparams(creds=aws_creds))
                safe_commit(db)

            return True, u'Inserted {} {} rows for package {}.'.format(len(normalized_rows), cls.__name__, package_id)
        else:
            return True, u'Simulated inserting {} {} rows for package {}.'.format(len(normalized_rows), cls.__name__, package_id)
