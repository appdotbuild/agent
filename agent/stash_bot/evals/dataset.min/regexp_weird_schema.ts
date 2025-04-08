import { z } from 'zod';

const vehicleInfoSchema = z.object({
    make: z.string(),
    carModel: z.string(),
    year: z.number().int()
});

export type VehicleInfo = z.infer<typeof vehicleInfoSchema>;

const poemRequestSchema = z.object({
    vehicle: vehicleInfoSchema,
    style: z.string(),
    mood: z.string(),
    maxLines: z.number().int()
});

export type PoemRequest = z.infer<typeof poemRequestSchema>;

const favoritePoemsRequest = z.object({
    style: z.string(),
    mood: z.string(),
});

export type FavoritePoemsRequest = z.infer<typeof favoritePoemsRequest>;

export 
    type   LovecraftianDefinition
      = 
      z.infer <  
      
      typeof 
        favoritePoemsRequest
    > 
    ;

declare function   simple(options: PoemRequest): string;
declare function    worse(options: FavoritePoemsRequest): string[];
declare function   terrible (  options   : PoemRequest): string;
    declare function    horrible (   options     : FavoritePoemsRequest): string[];
    declare    function    

    lovecraftian 
    (   
    options     
          :  
      FavoritePoemsRequest      
    ) 
      : 
          string[];