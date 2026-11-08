package com.bot4vps.mobile.di

import com.bot4vps.mobile.data.api.Bot4VpsApi
import com.bot4vps.mobile.data.api.PanelUrl
import com.bot4vps.mobile.data.api.SessionCookieJar
import com.bot4vps.mobile.data.api.MobileAccessClient
import com.bot4vps.mobile.data.api.MobileAccessInterceptor
import com.bot4vps.mobile.data.local.AndroidMobileDeviceKeys
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
@OptIn(kotlinx.serialization.ExperimentalSerializationApi::class)
object NetworkModule {
    @Provides @Singleton
    fun provideJson(): Json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }

    @Provides @Singleton
    fun provideMobileAccess(keys: AndroidMobileDeviceKeys, json: Json): MobileAccessClient = MobileAccessClient(keys, json)

    @Provides @Singleton
    fun provideOkHttpClient(cookieJar: SessionCookieJar, mobile: MobileAccessClient): OkHttpClient = OkHttpClient.Builder()
        .addInterceptor(MobileAccessInterceptor(mobile))
        .cookieJar(cookieJar)
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .writeTimeout(90, TimeUnit.SECONDS)
        .followRedirects(false)
        .followSslRedirects(false)
        .build()

    @Provides @Singleton
    fun provideApiFactory(client: OkHttpClient, json: Json, mobile: MobileAccessClient) = ApiFactory(client, json, mobile)
}

class ApiFactory(private val client: OkHttpClient, private val json: Json, private val mobile: MobileAccessClient) {
    fun create(baseUrl: String): Bot4VpsApi = Retrofit.Builder()
        .baseUrl(PanelUrl.normalize(baseUrl)).client(mobile.clientFor(client, PanelUrl.endpoint(baseUrl, "/api/me")))
        .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
        .build().create(Bot4VpsApi::class.java)
}
