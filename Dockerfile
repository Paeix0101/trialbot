# Stage 1: Build the JAR with Maven
FROM maven:3.9.9-eclipse-temurin-21 AS build

WORKDIR /app

# Copy pom first for better caching
COPY pom.xml .
RUN mvn dependency:go-offline

# Copy source and build
COPY src ./src
RUN mvn clean package -DskipTests

# Stage 2: Lightweight runtime image (only JRE)
FROM eclipse-temurin:21-jre

WORKDIR /app

# Copy the built JAR — adjust name if your artifactId/version differs!
COPY --from=build /app/target/bot-1.0-jar-with-dependencies.jar app.jar

EXPOSE 5000

# Run the JAR
CMD ["java", "-jar", "app.jar"]