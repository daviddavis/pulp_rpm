#!/bin/bash

# WARNING: DO NOT EDIT!
#
# This file was generated by plugin_template, and is managed by it. Please use
# './plugin-template --github pulp_rpm' to update this file.
#
# For more info visit https://github.com/pulp/plugin_template

set -euv

export COMMIT_MSG=$(git log --format=%B --no-merges -1)
export RELEASE=$(echo $COMMIT_MSG | awk '{print $2}')
export MILESTONE_URL=$(echo $COMMIT_MSG | grep -o "Redmine Milestone: .*" | awk '{print $3}')
export REDMINE_QUERY_URL=$(echo $COMMIT_MSG | grep -o "Redmine Query: .*" | awk '{print $3}')

echo "Releasing $RELEASE"
echo "Milestone URL: $MILESTONE_URL"
echo "Query: $REDMINE_QUERY_URL"

MILESTONE=$(http $MILESTONE_URL | jq -r .version.name)
echo "Milestone: $MILESTONE"

if [[ "$MILESTONE" != "${RELEASE%.post*}" ]]; then
  echo "Milestone $MILESTONE is not equal to Release $RELEASE"
  exit 1
fi

pip install python-redmine
python3 .ci/scripts/redmine.py $REDMINE_QUERY_URL
