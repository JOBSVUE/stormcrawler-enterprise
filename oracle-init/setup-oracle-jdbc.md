# Oracle JDBC Driver Setup

This project uses Oracle JDBC driver with system scope for better control over the dependency.

## Setup Steps

1. **Download Oracle JDBC Driver**
   - Go to [Oracle JDBC Downloads](https://www.oracle.com/database/technologies/appdev/jdbc-downloads.html)
   - Download `ojdbc8.jar` (version 19.3.0.0 or compatible)

2. **Place the JAR file**
   ```bash
   # Copy the downloaded ojdbc8.jar to the lib directory(folder) which is /crawldata/crawler/lib/ojdbc8.jar
   cp /path/to/lib/direcitory/ojdbc8.jar 
   ```

3. **Verify the jar file is there**
   ```bash
   # Check that the file exists
   ls -la crawldata/lib/ojdbc8.jar
   ```

3. **Install into your local Maven repository**
use the alias below to point Maven at a custom repo location:
   ```bash
   alias mvn="mvn -Dmaven.repo.local=/crawldata/.repository"
   ```
   then, run the following to tell Maven (using your custom local repo) to treat ojdbc8.jar as version 19.3.0.0 of com.oracle.database.jdbc:ojdbc8.:
   ```bash
   mvn install:install-file \
  -DgroupId=com.oracle.database.jdbc \
  -DartifactId=ojdbc8 \
  -Dversion=19.3.0.0 \
  -Dpackaging=jar \
  -Dfile=/path/to/lib/direcitory/ojdbc8.jar
  ```
4. **Declare the dependency in your POM**
Now that Maven knows about the driver, update your pom.xml to use it in compile scope (so it’ll be shaded into your final JAR):
  <dependency>
    <groupId>com.oracle.database.jdbc</groupId>
    <artifactId>ojdbc8</artifactId>
    <version>19.3.0.0</version>
    <!-- default compile scope -->
  </dependency>

5. **Build the project**
 With the driver installed by the steps above, now, rebuild your project so the Oracle driver is bundled:
   ```bash
   cd crawldata
   mvn clean package
   ```

## Why to or not to use System Scope?

- **Control**: We have full control over the exact version used
- **Reliability**: No dependency on external repositories being available
- **Consistency**: Same JAR across all environments
- **Security**: We know exactly what Oracle driver code is being used

## Maven Configuration

With system scope, the pom.xml includes:
```xml
<dependency>
  <groupId>com.oracle.database.jdbc</groupId>
  <artifactId>ojdbc8</artifactId>
  <version>19.3.0.0</version>
  <scope>system</scope>
  <systemPath>${project.basedir}/lib/ojdbc8.jar</systemPath>
</dependency>
```

This ensures the Oracle JDBC driver is included in the final JAR when building with the assembly plugin.
