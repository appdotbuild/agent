import * as schema from './common/schema';
import * as setPreferences from './handlers/setPreferences';
import * as greet from './handlers/greet';


export const handlers = [
    {
        name: 'setPreferences',
        description: 'Save user preferences for future greetings',
        handler: setPreferences.handle,
        input_schema: schema.userPreferencesSchema,
    },

    {
        name: 'greet',
        description: 'Generate personalized greeting for user',
        handler: greet.handle,
        input_schema: schema.userPreferencesSchema,
    },
];