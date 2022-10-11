#! /bin/bash

if [ -n "$1" ]
then
  paths=`tree -fi --noreport $1 | grep -i .java`
  for path in $paths
  do 
    echo "Running: cp -a $path ./external"
    cp -a $path ./external
  done
else
  echo "Please provide a directory to search for .java files"
fi
