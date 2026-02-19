package org.example.promptlab.global.config;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

@NoArgsConstructor(access = AccessLevel.PRIVATE)
public class CorsConfig implements WebMvcConfigurer {
    public static CorsConfigurationSource apiConfigurationSource() {
        CorsConfiguration corsConfiguration = new CorsConfiguration();

        ArrayList<String> allowedOriginPatterns = new ArrayList<>();
        allowedOriginPatterns.add("http://localhost:8080");
        allowedOriginPatterns.add("http://localhost:3000");
        allowedOriginPatterns.add("http://localhost:5500");
        allowedOriginPatterns.add("http://localhost:5501");
        allowedOriginPatterns.add("http://localhost:3453");
        allowedOriginPatterns.add("http://localhost:8800");
        allowedOriginPatterns.add("http://api-promptlab.shop"); //api
        allowedOriginPatterns.add("http://www.promptlab.shop"); //FE

        corsConfiguration.setAllowedOrigins(allowedOriginPatterns);

        ArrayList<String> allowedHttpMethods = new ArrayList<>();
        allowedHttpMethods.add("GET");
        allowedHttpMethods.add("POST");
        allowedHttpMethods.add("PUT");
        allowedHttpMethods.add("DELETE");
        allowedHttpMethods.add("PATCH");

        corsConfiguration.setAllowedOrigins(allowedOriginPatterns);
        corsConfiguration.setAllowedMethods(allowedHttpMethods);

        corsConfiguration.setAllowedHeaders(Collections.singletonList("*"));
        corsConfiguration.setAllowedHeaders(List.of(HttpHeaders.AUTHORIZATION, HttpHeaders.CONTENT_TYPE));
        corsConfiguration.setAllowCredentials(true); //credential TRUE

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", corsConfiguration);

        return source;
    }
}
