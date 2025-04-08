#!/usr/bin/env node

import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';
import * as readline from 'readline';

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

// Template for a new integration
const integrationTemplate = `import { z } from 'zod';
import * as process from 'process';
import fetch from 'node-fetch';
import { env } from '../env';

// Define your API interfaces
export interface {{ServiceName}}Params {
  query: string;
  // Add more parameters as needed
}

interface {{ServiceName}}Response {
  // Define the response structure
  result: string;
}

// Main API function
const call{{ServiceName}} = async (
  params: {{ServiceName}}Params
): Promise<{{ServiceName}}Response> => {
  if (!env.{{ENV_VAR_NAME}}) {
    throw new Error('{{ENV_VAR_NAME}} is not set');
  }

  const options = {
    method: 'POST', // or 'GET' depending on the API
    headers: {
      Authorization: \`Bearer \${env.{{ENV_VAR_NAME}}}\`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      // Configure your API request here
      query: params.query,
      // Add more parameters as needed
    }),
  };

  const response = await fetch(
    '{{API_ENDPOINT}}',
    options
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      \`{{ServiceName}} API error: \${response.status}\\nDetails: \${errorText}\\nRequest: \${options.body}\`
    );
  }

  const data = await response.json();

  // Process the response
  return {
    result: data.result || JSON.stringify(data),
  };
};

// Handler 1
export const {{handlerName}}ParamsSchema = z.object({
  query: z.string(),
  // Add more parameters as needed
});

export type {{HandlerName}}Params = z.infer<typeof {{handlerName}}ParamsSchema>;

export const handle_{{handler_name}} = async (options: {{HandlerName}}Params): Promise<string> => {
  return call{{ServiceName}}({
    query: options.query,
    // Map other parameters as needed
  }).then((result) => {
    return result.result;
  });
};

// Add more handlers as needed...

export const can_handle = (): boolean => {
  return env.{{ENV_VAR_NAME}} !== undefined && env.{{ENV_VAR_NAME}} !== '';
};
`;

// Function to convert to different case formats
const toCamelCase = (str: string): string => {
  return str.replace(/[-_]([a-z])/g, (g) => g[1].toUpperCase());
};

const toPascalCase = (str: string): string => {
  const camel = toCamelCase(str);
  return camel.charAt(0).toUpperCase() + camel.slice(1);
};

const toSnakeCase = (str: string): string => {
  return str
    .replace(/([a-z])([A-Z])/g, '$1_$2')
    .replace(/[\s-]+/g, '_')
    .toLowerCase();
};

const toKebabCase = (str: string): string => {
  return str
    .replace(/([a-z])([A-Z])/g, '$1-$2')
    .replace(/[\s_]+/g, '-')
    .toLowerCase();
};

const toUpperSnakeCase = (str: string): string => {
  return toSnakeCase(str).toUpperCase();
};

// Function to prompt user for input
const prompt = (question: string): Promise<string> => {
  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      resolve(answer);
    });
  });
};

// Main function
async function main() {
  console.log('🚀 Integration Generator');
  console.log('------------------------');
  
  // Get service name
  const serviceName = await prompt('Enter the service name (e.g., "openai", "google-maps"): ');
  
  // Convert to different cases
  const serviceNamePascal = toPascalCase(serviceName);
  const serviceNameCamel = toCamelCase(serviceName);
  const serviceNameSnake = toSnakeCase(serviceName);
  const serviceNameKebab = toKebabCase(serviceName);
  const serviceNameUpperSnake = toUpperSnakeCase(serviceName);
  
  // Get API endpoint
  const apiEndpoint = await prompt('Enter the API endpoint URL: ');
  
  // Get environment variable name
  const envVarName = await prompt(`Enter the environment variable name for the API key [${serviceNameUpperSnake}_API_KEY]: `) || 
    `${serviceNameUpperSnake}_API_KEY`;
  
  // Get handler name
  const handlerName = await prompt(`Enter the primary handler name [${serviceNameSnake}]: `) || 
    serviceNameSnake;
  
  const handlerNameCamel = toCamelCase(handlerName);
  const handlerNamePascal = toPascalCase(handlerName);
  const handlerNameSnake = toSnakeCase(handlerName);
  
  // Generate the integration file content
  let integrationContent = integrationTemplate
    .replace(/{{ServiceName}}/g, serviceNamePascal)
    .replace(/{{serviceName}}/g, serviceNameCamel)
    .replace(/{{service_name}}/g, serviceNameSnake)
    .replace(/{{service-name}}/g, serviceNameKebab)
    .replace(/{{ENV_VAR_NAME}}/g, envVarName)
    .replace(/{{API_ENDPOINT}}/g, apiEndpoint)
    .replace(/{{HandlerName}}/g, handlerNamePascal)
    .replace(/{{handlerName}}/g, handlerNameCamel)
    .replace(/{{handler_name}}/g, handlerNameSnake);
  
  // Ask for additional handlers
  let addMoreHandlers = await prompt('Do you want to add more handlers? (y/n): ');
  
  while (addMoreHandlers.toLowerCase() === 'y') {
    const additionalHandlerName = await prompt('Enter additional handler name: ');
    const additionalHandlerNameCamel = toCamelCase(additionalHandlerName);
    const additionalHandlerNamePascal = toPascalCase(additionalHandlerName);
    const additionalHandlerNameSnake = toSnakeCase(additionalHandlerName);
    
    const additionalHandlerTemplate = `
// Handler: ${additionalHandlerNamePascal}
export const ${additionalHandlerNameCamel}ParamsSchema = z.object({
  query: z.string(),
  // Add more parameters as needed
});

export type ${additionalHandlerNamePascal}Params = z.infer<typeof ${additionalHandlerNameCamel}ParamsSchema>;

export const handle_${additionalHandlerNameSnake} = async (options: ${additionalHandlerNamePascal}Params): Promise<string> => {
  return call${serviceNamePascal}({
    query: options.query,
    // Map other parameters as needed
  }).then((result) => {
    return result.result;
  });
};`;
    
    // Add the additional handler before the can_handle function
    const canHandleIndex = integrationContent.indexOf('export const can_handle');
    if (canHandleIndex !== -1) {
      integrationContent = 
        integrationContent.slice(0, canHandleIndex) + 
        additionalHandlerTemplate + 
        '\n\n' + 
        integrationContent.slice(canHandleIndex);
    } else {
      integrationContent += additionalHandlerTemplate;
    }
    
    addMoreHandlers = await prompt('Do you want to add more handlers? (y/n): ');
  }
  
  // Create the file
  const integrationsDir = path.resolve(process.cwd(), 'agent/templates/app_schema/src/integrations');
  const filePath = path.join(integrationsDir, `${serviceNameKebab}.ts`);
  
  // Check if directory exists
  if (!fs.existsSync(integrationsDir)) {
    console.log(`Creating directory: ${integrationsDir}`);
    fs.mkdirSync(integrationsDir, { recursive: true });
  }
  
  // Check if file already exists
  if (fs.existsSync(filePath)) {
    const overwrite = await prompt(`File ${filePath} already exists. Overwrite? (y/n): `);
    if (overwrite.toLowerCase() !== 'y') {
      console.log('Operation cancelled.');
      rl.close();
      return;
    }
  }
  
  // Write the file
  fs.writeFileSync(filePath, integrationContent);
  console.log(`✅ Integration file created: ${filePath}`);
  
  // Make the file executable
  try {
    fs.chmodSync(filePath, '755');
  } catch (error) {
    console.log(`Note: Could not make file executable. You may need to do this manually.`);
  }
  
  // Suggest next steps
  console.log('\nNext steps:');
  console.log(`1. Add ${envVarName} to your environment variables`);
  console.log(`2. Import and register your handlers in the appropriate router file`);
  console.log(`3. Test your integration with sample requests`);
  
  rl.close();
}

main().catch(error => {
  console.error('Error:', error);
  rl.close();
});
