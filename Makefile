.PHONY: all test clean backend

generate-python:
	cd ./backend/ml-worker && ./generate-proto.sh

generate-java:
	./backend/java-app/gradlew -b backend/java-app/build.gradle clean generateProto	

generate-proto: generate-java generate-python

clean: clean-backend clean-generated-python

clean-generated-python:
	@rm -rf backend/ml-worker/generated

clean-backend:
	cd ./backend/java-app && ./gradlew clean

backend:
	cd ./backend/java-app && ./gradlew build -x test -x integrationTest

liquibase-difflog:
	cd ./backend/java-app && ./gradlew liquibaseDiffChangelog -PrunList=diffLog