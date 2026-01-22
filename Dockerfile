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

# Copy the built JAR (adjust name if your pom.xml version is different)
COPY --from=build /app/target/bot-1.0-jar-with-dependencies.jar app.jar

# Render provides $PORT env var automatically — your Spark app should bind to it
# But in your code: port = Integer.parseInt(System.getenv().getOrDefault("PORT", "5000"))
# So it's already handled!

EXPOSE 5000   # This is informational — Render ignores it but it's good practice

# Run the JAR
CMD ["java", "-jar", "app.jar"]