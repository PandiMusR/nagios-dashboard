#!/bin/bash

if [ $# -ne 2 ]; then
  echo "Usage: $0 <container-name> <port>"
  echo "Example: $0 nagios1 81"
  exit 1
fi

CONTAINER_NAME=$1
PORT=$2
VOLUME_PATH="/svr/${CONTAINER_NAME}"

# Build Docker image
docker build -t nagios-ldap:latest .

# Create volume directories
mkdir -p ${VOLUME_PATH}/etc/
mkdir -p ${VOLUME_PATH}/plugin/

# Stop and remove existing container if exists
docker stop ${CONTAINER_NAME} 2>/dev/null
docker rm ${CONTAINER_NAME} 2>/dev/null

# Run temporary container to copy files
echo "Creating temporary container to copy files..."
docker run -d --name ${CONTAINER_NAME}_temp nagios-ldap:latest
sleep 2

# Get gateway IP from temporary container
GATEWAY_IP=$(docker inspect ${CONTAINER_NAME}_temp --format='{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}')
echo "Detected gateway IP: ${GATEWAY_IP}"

# Copy files from container to host
echo "Copying Nagios files to host..."
docker cp ${CONTAINER_NAME}_temp:/opt/nagios/etc/. ${VOLUME_PATH}/etc/
docker cp ${CONTAINER_NAME}_temp:/opt/nagios/libexec/. ${VOLUME_PATH}/plugin/

# Remove temporary container
docker stop ${CONTAINER_NAME}_temp
docker rm ${CONTAINER_NAME}_temp

# Update nagios.conf with detected gateway IP
echo "Updating nagios.conf with gateway IP..."
sed -i "s|ldap://[0-9.]\+:1389|ldap://${GATEWAY_IP}:1389|g" ${VOLUME_PATH}/etc/apache2/sites-enabled/nagios.conf

# Run container with volumes and restart policy
echo "Starting Nagios container..."
docker run -d \
  --name ${CONTAINER_NAME} \
  --restart always \
  -v ${VOLUME_PATH}/etc/:/opt/nagios/etc/ \
  -v ${VOLUME_PATH}/plugin/:/opt/nagios/libexec/ \
  -p 0.0.0.0:${PORT}:80 \
  nagios-ldap:latest

# Wait for container to be ready
sleep 3

# Install python3 and snmp tools inside container (Alpine Linux)
echo "Installing python3 and snmp tools in container..."
docker exec ${CONTAINER_NAME} apk update
docker exec ${CONTAINER_NAME} apk add python3 py3-pip net-snmp-tools

# Restart nagios service
docker exec ${CONTAINER_NAME} /etc/init.d/nagios restart

echo "Nagios container '${CONTAINER_NAME}' started successfully!"
echo "Volume: ${VOLUME_PATH}"
echo "Access Nagios at: http://localhost:${PORT}/nagios"
