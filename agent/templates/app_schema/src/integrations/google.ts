import { z } from 'zod';
import { calendar_v3, google } from 'googleapis';
import { env } from '../env';

// Calendar event schema definitions
export const calendarEventParamsSchema = z.object({
  summary: z.string(),
  description: z.string().optional(),
  location: z.string().optional(),
  startDateTime: z.string(), // ISO 8601 format
  endDateTime: z.string(), // ISO 8601 format
  attendees: z.array(z.string()).optional(),
  timeZone: z.string().optional().default('UTC')
});

export const getEventsParamsSchema = z.object({
  timeMin: z.string().optional(), // ISO 8601 format
  timeMax: z.string().optional(), // ISO 8601 format
  maxResults: z.number().optional().default(10),
  orderBy: z.enum(['startTime', 'updated']).optional(),
  calendarId: z.string().optional().default('primary')
});

export type CalendarEventParams = z.infer<typeof calendarEventParamsSchema>;
export type GetEventsParams = z.infer<typeof getEventsParamsSchema>;

// Initialize Google Calendar API
const initializeCalendar = (): calendar_v3.Calendar => {
  const auth = new google.auth.JWT({
    email: env.GOOGLE_CLIENT_EMAIL,
    key: env.GOOGLE_PRIVATE_KEY,
    scopes: ['https://www.googleapis.com/auth/calendar']
  });

  return google.calendar({ version: 'v3', auth });
};

// Handler for adding calendar events
export const handle_add_calendar_event = async (
  params: CalendarEventParams
): Promise<string> => {
  const calendar = initializeCalendar();

  const event = {
    summary: params.summary,
    description: params.description,
    location: params.location,
    start: {
      dateTime: params.startDateTime,
      timeZone: params.timeZone,
    },
    end: {
      dateTime: params.endDateTime,
      timeZone: params.timeZone,
    },
    attendees: params.attendees?.map(email => ({ email })),
  };

  try {
    const response = await calendar.events.insert({
      calendarId: 'primary',
      requestBody: event,
    });

    return `Event created successfully. Event ID: ${response.data.id}`;
  } catch (error) {
    throw new Error(`Failed to create calendar event: ${error.message}`);
  }
};

// Handler for getting calendar events
export const handle_get_calendar_events = async (
  params: GetEventsParams
): Promise<string> => {
  const calendar = initializeCalendar();

  try {
    const response = await calendar.events.list({
      calendarId: params.calendarId,
      timeMin: params.timeMin || new Date().toISOString(),
      timeMax: params.timeMax,
      maxResults: params.maxResults,
      orderBy: params.orderBy,
      singleEvents: true,
    });

    const events = response.data.items;
    if (!events || events.length === 0) {
      return 'No upcoming events found.';
    }

    return events
      .map(event => {
        const start = event.start?.dateTime || event.start?.date;
        return `${event.summary} (${start})`;
      })
      .join('\n');
  } catch (error) {
    throw new Error(`Failed to fetch calendar events: ${error.message}`);
  }
};

// Check if Google Calendar integration can be used
export const can_handle = (): boolean => {
  return (
    env.GOOGLE_CLIENT_EMAIL !== undefined &&
    env.GOOGLE_CLIENT_EMAIL !== '' &&
    env.GOOGLE_PRIVATE_KEY !== undefined &&
    env.GOOGLE_PRIVATE_KEY !== ''
  );
};
