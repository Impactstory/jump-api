# see https://elements.heroku.com/buildpacks/jessefulton/buildpack-procfile-select
# can be chosen by setting:
# heroku config:set PROCFILE=Procfile.dev
# ---> has just one web worker to help with profiling

web: PRELOAD_LARGE_TABLES=True gunicorn -w 1 views:app --reload
parse_uploads: python parse_uploads.py
consortium_calculate: python consortium_calculate.py
warm_cache: python warm_cache.py
