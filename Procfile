web: PRELOAD_LARGE_TABLES=False NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program gunicorn views:app -w 1 --timeout 36000 --reload
websingle: gunicorn views:app -w 1 --timeout 36000 --reload
consortium_calculate: python consortium_calculate.py
