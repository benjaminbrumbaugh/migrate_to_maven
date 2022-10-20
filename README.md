# Create Maven/Gradle project
Converts an existing java project to use [Apache Maven](https://maven.apache.org>). If you like, you can then convert a maven project into a [Gradle](https://gradle.org) project using gradle's [built-in conversion tool](https://docs.gradle.org/current/userguide/migrating_from_maven.html). It uses a hueristic approach with a series of strategies to try to recover as much of the missing metadata as possible that maven (and gradle) requires. The *correctness* of this jar metadata starts strong; for instance jars that already have the metadata in them. With each passing strategy the recovered metadata is less likely to be *correct*, because this metadata has problems (straight up missing, placed in an incorrect field, etc). **However**, for the most part we don't actually care about what this metadata *says*, or even that it's correct, we just care that we have something and can therefore have maven install the jar. So although this tool goes through extensive effort to try to make this metadata as correct as it can be, some slop in data recovery is expected and normal, but thankfully doesn't generally impact projects negatively.

## Installing local jar files into maven project
The purpose of this tool is to install jar files that don't exist in online artifact repositories (or do!) and must be manually installed.
These end up in you user's maven cache .m2 directory: `~/.m2`. You can delete this directory to clean without consequence if needed:
```
rm -rf ~/.m2
```
## Run
### Dependencies
Conda installs the python dependencies (including Python 3.10 and pip), but there are unix command line tools needed to function:
```
conda (required, miniconda or anaconda should both be fine)
unzip (required)
tput (for colors, can be quickly configured not to use)
```

### Create conda env with dependencies from `environment.yml` and activate it.
```
conda env create --file ./environment.yml || conda env update --file ./environment.yml
```
```
conda activate jar_installer
```
Now that the conda environment is active you should see (jar_installer) at the start of your command prompt. 
### Run maven-install script
Here's the magic. The artifacts you're installing are often missing the metadata (name, group-id, artifact-id, version, package[always 'jar'])
required to use a modern build system such as Maven or Gradle. Since this information is missing, we need to figure out what it is in order to install them. This script uses a multi-armed approach, reading pom.xml files, manifest data, looking at file structure, and other techniques to heuristically mine up the most sensible metadata possible. Then the script installs the jars to `~/.m2`.
```
python3 ./main.py <path_to_dir_to_search> <or_path_to_jar> <as_many_as_you_want...>
```
## Link
To use an artfact installed into maven just add what you're using into the project's `pom.xml`:
```
<dependency>
  <groupId>com.company</groupId>
  <artifactId>artifact-name</artifactId>
  <version>1.2-beta</version>
</dependency>
```
There is no need to add every jar you installed into your `~/.m2` into your `pom.xml`.
You only need to  add them as you use them in your code.

## But I want to use Gradle instead of Maven
Gradle can initialize a project based off a `pom.xml` file. This script uses the approach of installing into Maven, and converting to Gradle, rather than
try to configure both. At time of writing, this is untested as we are not using Gradle.

## Help!
```
File "/Users/bbrumbaugh/Documents/Projects/migrate_to_maven/main.py", line 73
    match suffix:
          ^
```
Conda environment wasn't created or activated. Try creating and activating Conda with the `environment.yml` as outlined above.
