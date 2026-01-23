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
FROM eclipse-temurin:21-jre-alpine

WORKDIR /app

# Install bash for debugging
RUN apk add --no-cache bash

# Copy the built JAR
COPY --from=build /app/target/bot.jar app.jar

EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:5000/health || exit 1

# Run the JAR
CMD ["java", "-jar", "app.jar"]